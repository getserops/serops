#!/usr/bin/env python3
"""Save everything about each incident of a benchmark estate run, so that
"was the evidence readable, and did SerOps read it" can be answered later
from saved data, after the estate is gone.

    python3 tools/estate-capture/capture.py <estate-dir> [--only J2-r1 ...] [--force]

<estate-dir> holds the run (``results/<incident>-<round>-{inject,investigation,revert}.json``,
written by the estate's incident runner) and a ``capture.json`` describing the
estate: SerOps' URL and token files, the kubeconfig, the stores and the output
directory. See README.md next to this file.

Per incident and round, one directory ``<output>/<estate>/<incident>-<round>/``:

    analysis.json          the investigation, the batch (what SerOps fed the AI),
                           its issues, timeline and analysis history, model, tokens
    query-trail.jsonl.gz   every request SerOps sent to a store and the answer
                           (needs SEROPS_QUERY_TRAIL_DIR on the SerOps workers)
    <store>.json.gz        what each store held for the window, read directly:
                           every metric series with all its labels; logs (all
                           levels) and traces of the incident's services
    injection.json         what was broken, when, the pre-registered key
    versions.json          SerOps version and commit, estate setup commit, model
    manifest.json          written last: files, sizes, sha256, counts, windows,
                           truncation, redaction counts, secret scan result

Rules it keeps:
- everything is run through SerOps' own redaction (backend/Utils/data_redaction.py)
  before it is written, then scanned for credentials, tokens and kubeconfig
  material; a hit discards the incident and exits non-zero;
- a store that cannot be read, or answers nothing at all, stops the incident
  with an error; nothing is saved half-empty;
- safe to run twice: a complete capture (manifest.json present) is skipped
  unless --force; an incident is written to a temporary directory and moved
  into place only when complete.

Python 3.8+, standard library only, plus kubectl (Kubernetes stores and the
trail), docker (trail on a Docker estate) and openssl (Google Cloud Monitoring).
"""
import argparse
import base64
import concurrent.futures
import gzip
import hashlib
import json
import math
import os
import re
import select
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, '..', '..', 'backend'))

DEFAULT_MARGIN_MINUTES = 5
MAX_WINDOW_MINUTES = 90
PAGE = 5000


class CaptureError(Exception):
    """A store, the API or a check failed: the incident is not saved."""


class SecretFound(CaptureError):
    """A secret survived redaction. The whole run stops at once, so the
    incident is not passed over unnoticed among the others: fix the cause and
    capture it again while the estate is still up."""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def parse_time(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def http(method, url, params=None, body=None, headers=None, timeout=120, insecure=False, raw=False):
    if params:
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params, doseq=True)
    if body is not None and not isinstance(body, bytes):
        body = (body if isinstance(body, str) else json.dumps(body)).encode()
    hdrs = {'Accept': 'application/json'}
    if body is not None:
        hdrs['Content-Type'] = 'application/json'
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    ctx = ssl._create_unverified_context() if insecure else None   # noqa: S323 (in-cluster self-signed)
    shown = url.split('?', 1)[0]
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode('utf-8', 'replace')
        raise CaptureError(f'{method} {shown}: HTTP {exc.code}: {detail}') from None
    except (urllib.error.URLError, OSError) as exc:
        raise CaptureError(f'{method} {shown}: {exc}') from None
    if raw:
        return payload
    try:
        return json.loads(payload or b'null')
    except ValueError:
        raise CaptureError(f'{method} {shown}: the answer is not JSON') from None


# --------------------------------------------------------------------------
# Kubernetes / Docker access
# --------------------------------------------------------------------------

class Access:
    """Port-forwards to in-cluster stores; closed on exit."""

    def __init__(self, kubeconfig):
        self.kubeconfig = kubeconfig
        self.procs = []
        self.urls = {}

    def kubectl(self, *args, check=True, timeout=120):
        if not self.kubeconfig:
            raise CaptureError('this estate has no kubeconfig in capture.json')
        res = subprocess.run(['kubectl', '--kubeconfig', self.kubeconfig] + list(args),
                             capture_output=True, text=True, timeout=timeout)
        if check and res.returncode != 0:
            raise CaptureError(f'kubectl {" ".join(args[:3])}: {res.stderr.strip()[:300]}')
        return res

    def forward(self, service, port, scheme='http'):
        """``service`` is ``<namespace>/<svc|pod|deploy>/<name>``; returns a base URL."""
        key = (service, port)
        if key in self.urls:
            return self.urls[key]
        try:
            ns, target = service.split('/', 1)
        except ValueError:
            raise CaptureError(f'store service must be namespace/svc/name, got {service!r}') from None
        if not self.kubeconfig:
            raise CaptureError('this estate has no kubeconfig in capture.json')
        proc = subprocess.Popen(['kubectl', '--kubeconfig', self.kubeconfig, '-n', ns, 'port-forward',
                                 target, f':{port}'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.procs.append(proc)
        ready, _, _ = select.select([proc.stdout], [], [], 30)
        line = proc.stdout.readline() if ready else ''
        match = re.search(r'127\.0\.0\.1:(\d+)', line)
        if not match:
            proc.terminate()
            err = proc.stderr.read()[:300] if proc.poll() is not None else 'no answer in 30 s'
            raise CaptureError(f'port-forward to {service}:{port} failed: {err}')
        # Drain kubectl's output so its pipe never fills up.
        threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
        url = f'{scheme}://127.0.0.1:{match.group(1)}'
        self.urls[key] = url
        return url

    def close(self):
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()


# --------------------------------------------------------------------------
# Estate configuration
# --------------------------------------------------------------------------

class Estate:
    def __init__(self, directory):
        self.dir = os.path.abspath(directory)
        path = os.path.join(self.dir, 'capture.json')
        if not os.path.exists(path):
            raise CaptureError(f'{path} not found (see tools/estate-capture/README.md)')
        with open(path) as f:
            self.cfg = json.load(f)
        for key in ('estate', 'output', 'serops', 'stores'):
            if key not in self.cfg:
                raise CaptureError(f'capture.json: "{key}" is required')
        self.name = self.cfg['estate']
        self.output = os.path.expanduser(self.cfg['output'])
        repo = os.path.normpath(os.path.join(HERE, '..', '..'))
        if os.path.abspath(self.output).startswith(repo + os.sep):
            raise CaptureError('output must be outside the repository')
        if '/common/' in os.path.abspath(self.output) + '/':
            raise CaptureError('output must be outside common/')
        api = self.cfg['serops']
        self.api_base = self.read(api.get('base_url_file', 'base_url')).rstrip('/')
        self.token = self.read(api.get('token_file', 'token'))
        kc = self.cfg.get('kubeconfig')
        self.kubeconfig = self.path(kc) if kc else None
        self.results = self.path(self.cfg.get('results_dir', 'results'))

    def path(self, rel):
        return rel if os.path.isabs(rel) else os.path.join(self.dir, rel)

    def read(self, rel):
        with open(self.path(rel)) as f:
            return f.read().strip()

    def api(self, path, params=None):
        return http('GET', self.api_base + path, params=params,
                    headers={'Authorization': f'Token {self.token}'})

    def secrets(self):
        """Every secret value this estate holds, to make sure none is saved."""
        values = {self.token}
        names = ['token'] + list(self.cfg.get('secret_files', []))
        for rel in names:
            p = self.path(rel)
            if not os.path.exists(p):
                continue
            with open(p, errors='replace') as f:
                text = f.read()
            for line in text.splitlines():
                if '=' in line and not line.lstrip().startswith('#'):
                    values.add(line.split('=', 1)[1].strip().strip('"\''))
                values.add(line.strip())
        if self.kubeconfig and os.path.exists(self.kubeconfig):
            with open(self.kubeconfig, errors='replace') as f:
                for m in re.finditer(r'(?:client-key-data|client-certificate-data|token|password):\s*(\S+)',
                                     f.read()):
                    values.add(m.group(1).strip('"\''))
        return {v for v in values if v and len(v) >= 8}


# --------------------------------------------------------------------------
# Stores
# --------------------------------------------------------------------------

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _auth_headers(estate, store):
    auth = store.get('auth')
    if not auth:
        return {}
    env = {}
    with open(estate.path(auth['file'])) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                env[k] = v.strip('"\'')
    if auth.get('type', 'basic') == 'basic':
        pair = f"{env[auth['user']]}:{env[auth['password']]}".encode()
        return {'Authorization': 'Basic ' + base64.b64encode(pair).decode()}
    return {'Authorization': f"Bearer {env[auth['token']]}"}


def store_base(store, access):
    if store.get('url'):
        return store['url'].rstrip('/')
    if store.get('service'):
        return access.forward(store['service'], store['port'], store.get('scheme', 'http'))
    return None


def capture_prometheus(estate, store, base, services, start, end):
    """Every series of every metric in the window, all labels kept."""
    prefix = base + store.get('path', '')
    hdrs = _auth_headers(estate, store)
    insecure = store.get('insecure', False)
    span = {'start': iso(start), 'end': iso(end)}
    names = http('GET', prefix + '/api/v1/label/__name__/values', params=span, headers=hdrs, insecure=insecure)
    if not isinstance(names, dict) or names.get('status') != 'success':
        raise CaptureError(f"{store['name']}: metric names: {str(names)[:200]}")
    names = names.get('data') or []
    if not names:
        raise CaptureError(f"{store['name']}: no metric at all in {span['start']}..{span['end']}")
    step = int(store.get('step', 15))

    def one(name):
        esc = name.replace('\\', '\\\\').replace('"', '\\"')
        res = http('GET', prefix + '/api/v1/query_range', headers=hdrs, insecure=insecure,
                   params={'query': '{__name__="%s"}' % esc, 'step': step, **span})
        if res.get('status') != 'success':
            raise CaptureError(f"{store['name']}: {name}: {str(res)[:200]}")
        return [{'labels': s.get('metric', {}),
                 'values': [[int(float(t)), _num(v)] for t, v in s.get('values', [])]}
                for s in res['data']['result']]

    series = []
    with concurrent.futures.ThreadPoolExecutor(int(store.get('parallel', 8))) as pool:
        for chunk in pool.map(one, names):
            series.extend(chunk)
    if not series:
        raise CaptureError(f"{store['name']}: {len(names)} metric names but no series in the window")
    return {'kind': 'prometheus', 'step_seconds': step, 'metric_names': len(names),
            'series_count': len(series), 'series': series}, False


def capture_loki(estate, store, base, services, start, end):
    """All lines (every level) of each service in the window."""
    hdrs = _auth_headers(estate, store)
    cap = int(store.get('max_lines_per_service', 200000))
    out, truncated = {}, False
    for svc in services:
        selector = store['selector'].replace('SERVICE', svc)
        cursor, end_ns = int(start.timestamp() * 1e9), int(end.timestamp() * 1e9)
        streams, count, cut = {}, 0, False
        while True:
            res = http('GET', base + '/loki/api/v1/query_range', headers=hdrs,
                       params={'query': selector, 'start': cursor, 'end': end_ns,
                               'limit': PAGE, 'direction': 'forward'})
            if res.get('status') != 'success':
                raise CaptureError(f"{store['name']}: {selector}: {str(res)[:200]}")
            page = []
            for s in res['data']['result']:
                key = json.dumps(s.get('stream', {}), sort_keys=True)
                for ts, line in s.get('values', []):
                    page.append((int(ts), key, line))
            if not page:
                break
            for ts, key, line in page:
                streams.setdefault(key, []).append([ts, line])
            count += len(page)
            if len(page) < PAGE:
                break
            if count >= cap:
                cut = truncated = True
                break
            cursor = max(p[0] for p in page) + 1
        out[svc] = {'selector': selector, 'lines': count, 'truncated': cut,
                    'streams': [{'labels': json.loads(k), 'values': sorted(v)} for k, v in streams.items()]}
    if not any(v['lines'] for v in out.values()):
        raise CaptureError(f"{store['name']}: no log line at all for {', '.join(services)}")
    return {'kind': 'loki', 'services': out}, truncated


def capture_search(estate, store, base, services, start, end):
    """Elasticsearch / OpenSearch: every document of each service in the window."""
    hdrs = _auth_headers(estate, store)
    insecure = store.get('insecure', False)
    tf = store.get('time_field', '@timestamp')
    index = urllib.parse.quote(store['index'], safe='*,-_.')
    cap = int(store.get('max_lines_per_service', 200000))
    out, truncated = {}, False
    for svc in services:
        clause = json.loads(store['service_filter'].replace('SERVICE', json.dumps(svc)[1:-1]))
        body = {'size': PAGE, 'sort': [{tf: 'asc'}],
                'query': {'bool': {'filter': [{'range': {tf: {'gte': iso(start), 'lte': iso(end)}}}, clause]}}}
        res = http('POST', f'{base}/{index}/_search', params={'scroll': '2m'}, body=body,
                   headers=hdrs, insecure=insecure)
        docs, scroll_id, cut = [], res.get('_scroll_id'), False
        try:
            while True:
                hits = (res.get('hits') or {}).get('hits') or []
                if not hits:
                    break
                docs.extend({'index': h.get('_index'), 'source': h.get('_source')} for h in hits)
                if len(docs) >= cap:
                    cut = truncated = True
                    break
                res = http('POST', f'{base}/_search/scroll', body={'scroll': '2m', 'scroll_id': scroll_id},
                           headers=hdrs, insecure=insecure)
                scroll_id = res.get('_scroll_id') or scroll_id
        finally:
            if scroll_id:
                try:
                    http('DELETE', f'{base}/_search/scroll', body={'scroll_id': [scroll_id]},
                         headers=hdrs, insecure=insecure)
                except CaptureError:
                    pass
        out[svc] = {'filter': clause, 'documents': len(docs), 'truncated': cut, 'docs': docs}
    if not any(v['documents'] for v in out.values()):
        raise CaptureError(f"{store['name']}: no document at all for {', '.join(services)}")
    return {'kind': store['kind'], 'index': store['index'], 'services': out}, truncated


def capture_tempo(estate, store, base, services, start, end):
    hdrs = _auth_headers(estate, store)
    cap = int(store.get('max_traces_per_service', 300))
    tag = store.get('service_attribute', 'resource.service.name')
    out, truncated = {}, False
    for svc in services:
        params = {'start': int(start.timestamp()), 'end': int(end.timestamp()), 'limit': cap,
                  'q': '{%s="%s"}' % (tag, svc)}
        try:
            res = http('GET', base + '/api/search', params=params, headers=hdrs)
        except CaptureError as exc:
            if 'HTTP 400' not in str(exc):
                raise
            params.pop('q')
            params['tags'] = f"{tag.split('.', 1)[-1]}={svc}"
            res = http('GET', base + '/api/search', params=params, headers=hdrs)
        ids = [t['traceID'] for t in res.get('traces') or [] if t.get('traceID')]
        traces = [{'trace_id': i, 'trace': http('GET', f'{base}/api/traces/{i}', headers=hdrs)} for i in ids]
        cut = len(ids) >= cap
        truncated = truncated or cut
        out[svc] = {'traces': len(traces), 'truncated': cut, 'items': traces}
    if not any(v['traces'] for v in out.values()):
        raise CaptureError(f"{store['name']}: no trace at all for {', '.join(services)}")
    return {'kind': 'tempo', 'services': out}, truncated


def capture_jaeger(estate, store, base, services, start, end):
    hdrs = _auth_headers(estate, store)
    cap = int(store.get('max_traces_per_service', 300))
    out, truncated = {}, False
    for svc in services:
        res = http('GET', base + '/api/traces', headers=hdrs,
                   params={'service': svc, 'start': int(start.timestamp() * 1e6),
                           'end': int(end.timestamp() * 1e6), 'limit': cap})
        items = res.get('data') or []
        cut = len(items) >= cap
        truncated = truncated or cut
        out[svc] = {'traces': len(items), 'truncated': cut, 'items': items}
    if not any(v['traces'] for v in out.values()):
        raise CaptureError(f"{store['name']}: no trace at all for {', '.join(services)}")
    return {'kind': 'jaeger', 'services': out}, truncated


def capture_serops_traces(estate, store, base, services, start, end):
    """Spans SerOps received itself over OTLP, read through its API."""
    cap = int(store.get('max_traces_per_service', 300))
    out, truncated = {}, False
    for svc in services:
        ids, page = [], 1
        while len(ids) < cap:
            res = estate.api('/traces/traces/', params={'service': svc, 'since': iso(start),
                                                        'until': iso(end), 'page': page})
            rows = res.get('results', res) if isinstance(res, dict) else res
            ids.extend(r['trace_id'] for r in rows or [])
            if not isinstance(res, dict) or not res.get('next'):
                break
            page += 1
        cut = len(ids) >= cap
        truncated = truncated or cut
        items = [estate.api(f'/traces/traces/{i}/') for i in ids[:cap]]
        out[svc] = {'traces': len(items), 'truncated': cut, 'items': items}
    if not any(v['traces'] for v in out.values()):
        raise CaptureError(f"{store['name']}: no trace at all for {', '.join(services)}")
    return {'kind': 'serops-traces', 'services': out}, truncated


def _gcp_token(estate, store):
    with open(estate.path(store['key_file'])) as f:
        key = json.load(f)
    now = int(time.time())

    def b64(obj):
        raw = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()

    unsigned = b64({'alg': 'RS256', 'typ': 'JWT'}) + '.' + b64({
        'iss': key['client_email'], 'aud': key['token_uri'], 'iat': now, 'exp': now + 3000,
        'scope': 'https://www.googleapis.com/auth/monitoring.read'})
    tmp = tempfile.mkdtemp(prefix='capture-')
    try:
        pem = os.path.join(tmp, 'k.pem')
        fd = os.open(pem, os.O_WRONLY | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(key['private_key'])
        sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', pem], input=unsigned.encode(),
                             capture_output=True, check=True).stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    body = urllib.parse.urlencode({'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                                   'assertion': unsigned + '.' + b64(sig)}).encode()
    res = http('POST', key['token_uri'], body=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
    return res['access_token']


def capture_gcp_monitoring(estate, store, base, services, start, end):
    """Every series of every metric type under the configured prefixes."""
    hdrs = {'Authorization': f'Bearer {_gcp_token(estate, store)}'}
    root = f"https://monitoring.googleapis.com/v3/projects/{store['project']}"

    def pages(path, params):
        params, items = dict(params), []
        while True:
            res = http('GET', root + path, params=params, headers=hdrs)
            items.extend(res.get('metricDescriptors') or res.get('timeSeries') or [])
            if not res.get('nextPageToken'):
                return items
            params['pageToken'] = res['nextPageToken']

    types = []
    for prefix in store.get('prefixes', ['kubernetes.io/']):
        types += [d['type'] for d in pages('/metricDescriptors',
                                           {'filter': f'metric.type = starts_with("{prefix}")'})]
    if not types:
        raise CaptureError(f"{store['name']}: no metric type under {store.get('prefixes')}")
    extra = store.get('filter', '')

    def one(mtype):
        flt = f'metric.type = "{mtype}"' + (f' AND {extra}' if extra else '')
        return pages('/timeSeries', {'filter': flt, 'interval.startTime': iso(start),
                                     'interval.endTime': iso(end), 'view': 'FULL'})

    series = []
    with concurrent.futures.ThreadPoolExecutor(int(store.get('parallel', 8))) as pool:
        for chunk in pool.map(one, types):
            series.extend(chunk)
    if not series:
        raise CaptureError(f"{store['name']}: {len(types)} metric types but no series in the window")
    return {'kind': 'gcp-monitoring', 'metric_types': len(types), 'series_count': len(series),
            'series': series}, False


CAPTURERS = {
    'prometheus': capture_prometheus, 'mimir': capture_prometheus, 'victoriametrics': capture_prometheus,
    'loki': capture_loki, 'elasticsearch': capture_search, 'opensearch': capture_search,
    'tempo': capture_tempo, 'jaeger': capture_jaeger, 'serops-traces': capture_serops_traces,
    'gcp-monitoring': capture_gcp_monitoring,
}


# --------------------------------------------------------------------------
# Query trail
# --------------------------------------------------------------------------

def fetch_trail(estate, access, keys):
    trail = estate.cfg.get('trail')
    if not trail:
        return None
    directory = trail.get('dir', '/tmp/serops-query-trail')
    lines = []
    if trail.get('source', 'kubectl') == 'kubectl':
        ns = trail.get('namespace', 'serops')
        pods = access.kubectl('-n', ns, 'get', 'pods', '-l', trail['selector'], '-o', 'name').stdout.split()
        if not pods:
            raise CaptureError(f"no pod matches {trail['selector']} in {ns}")
        for pod in pods:
            for key in keys:
                res = access.kubectl('-n', ns, 'exec', pod, '--', 'cat', f'{directory}/{key}.jsonl', check=False)
                if res.returncode == 0:
                    lines += [l for l in res.stdout.splitlines() if l.strip()]
                elif 'No such file' not in res.stderr:
                    raise CaptureError(f'reading the trail on {pod}: {res.stderr.strip()[:300]}')
    else:
        for container in trail['containers']:
            for key in keys:
                res = subprocess.run(['docker', 'exec', container, 'cat', f'{directory}/{key}.jsonl'],
                                     capture_output=True, text=True)
                if res.returncode == 0:
                    lines += [l for l in res.stdout.splitlines() if l.strip()]
                elif 'No such file' not in res.stderr:
                    raise CaptureError(f'reading the trail in {container}: {res.stderr.strip()[:300]}')
    if not lines:
        raise CaptureError(f'no query trail for {", ".join(keys)}: is SEROPS_QUERY_TRAIL_DIR set on the '
                           'SerOps workers, and were they restarted since the run?')
    entries = [json.loads(l) for l in lines]
    entries.sort(key=lambda e: e.get('at') or '')
    return entries


# --------------------------------------------------------------------------
# Redaction and the secret check
# --------------------------------------------------------------------------

class Redactor:
    """SerOps' own redaction, applied to every string value."""

    def __init__(self):
        sys.path.insert(0, BACKEND)
        try:
            from Utils.data_redaction import DataRedactionService
        except Exception as exc:                        # noqa: BLE001
            raise CaptureError(f'cannot load SerOps redaction from {BACKEND}: {exc}') from None
        self.service = DataRedactionService()
        self.cache = {}
        self.counts = {}

    def text(self, value):
        hit = self.cache.get(value)
        if hit is None:
            redacted, findings = self.service.redact(value)
            hit = (redacted, [f.pattern_type for f in findings])
            if len(value) < 512:
                self.cache[value] = hit
        for kind in hit[1]:
            self.counts[kind] = self.counts.get(kind, 0) + 1
        return hit[0]

    def walk(self, obj):
        if isinstance(obj, str):
            return self.text(obj)
        if isinstance(obj, dict):
            return {k: self.walk(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.walk(v) for v in obj]
        return obj


SECRET_PATTERNS = {
    'private key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'kubeconfig': re.compile(r'client-(?:key|certificate)-data|certificate-authority-data'),
    'bearer token': re.compile(r'Bearer\s+[A-Za-z0-9._~+/=-]{16,}'),
    'basic auth': re.compile(r'Basic\s+[A-Za-z0-9+/]{16,}={0,2}'),
    'JWT': re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'),
    'Anthropic key': re.compile(r'sk-ant-[A-Za-z0-9_-]{16,}'),
    'OpenAI key': re.compile(r'sk-(?:proj-)?[A-Za-z0-9]{32,}'),
    'Google API key': re.compile(r'AIza[0-9A-Za-z_-]{35}'),
    'Google service account': re.compile(r'"private_key_id"\s*:'),
    'AWS key': re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'),
    'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})'),
    'GitLab token': re.compile(r'\bglpat-[A-Za-z0-9_-]{20,}'),
    'Slack token': re.compile(r'\bxox[abposr]-[A-Za-z0-9-]{10,}'),
    'Slack webhook': re.compile(r'hooks\.slack\.com/services/[A-Za-z0-9/]+'),
}


def secret_hits(text, known):
    hits = [name for name, rx in SECRET_PATTERNS.items() if rx.search(text)]
    hits += ['a secret of this estate (exact match)' for v in known if v in text][:1]
    return hits


# --------------------------------------------------------------------------
# One incident
# --------------------------------------------------------------------------

def incident_key(estate, incident):
    """The pre-registered key row of an incident, from a markdown table."""
    path = estate.cfg.get('keys_file')
    if not path:
        return None
    with open(estate.path(path)) as f:
        rows = [l for l in f if l.startswith('|')]
    header = next((l for l in rows if 'Incident' in l or 'incident' in l), rows[0] if rows else '')
    row = next((l for l in rows if l.split('|')[1].strip() == incident), None)
    if row is None:
        raise CaptureError(f'no key row for {incident} in {path}')
    return {'file': os.path.basename(path), 'header': header.strip(), 'row': row.strip()}


def setup_commit(estate):
    setup = estate.cfg.get('setup_dir')
    if not setup:
        raise CaptureError('capture.json: "setup_dir" (the git checkout the estate was set up from) is required')
    d = estate.path(setup)
    head = subprocess.run(['git', '-C', d, 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if head.returncode != 0:
        raise CaptureError(f'{d} is not a git checkout with a commit: {head.stderr.strip()[:200]}')
    dirty = subprocess.run(['git', '-C', d, 'status', '--porcelain'], capture_output=True, text=True).stdout
    return {'dir': os.path.basename(d.rstrip('/')), 'commit': head.stdout.strip(),
            'uncommitted_changes': len([l for l in dirty.splitlines() if l.strip()])}


def model_in_use(estate, batch, inv):
    """The model that answered. The batch records only the provider
    ("claude"), so the model id comes from the AI settings; a settings change
    after the investigation finished makes that unreliable, which is an error."""
    settings = estate.api('/settings/ai/')
    providers = estate.api('/settings/ai/providers/')
    providers = providers.get('results', providers) if isinstance(providers, dict) else providers
    default = next((p for p in providers or [] if p.get('id') == settings.get('default_provider')), {})
    changed = parse_time(settings.get('updated_at'))
    finished = parse_time(inv.get('finished_at'))
    if changed and finished and changed > finished:
        raise CaptureError(f"the AI settings changed at {settings.get('updated_at')}, after the investigation "
                           'finished; the model that answered cannot be read from them')
    return {'batch_records': (batch or {}).get('model_name'), 'provider': default.get('name'),
            'model': default.get('default_model'), 'source': 'AI settings at capture time, unchanged since '
            'the investigation finished', 'settings_updated_at': settings.get('updated_at')}


def load(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, obj, gz=False):
    data = json.dumps(obj, indent=None if gz else 1, sort_keys=False, default=str).encode()
    if gz:
        with open(path, 'wb') as f:
            # mtime=0: the same capture gives the same bytes.
            with gzip.GzipFile(fileobj=f, mode='wb', mtime=0) as g:
                g.write(data)
    else:
        with open(path, 'wb') as f:
            f.write(data)
    return data


def capture_incident(estate, access, incident, rnd, force=False):
    tag = f'{incident}-{rnd}'
    final = os.path.join(estate.output, estate.name, tag)
    if os.path.exists(os.path.join(final, 'manifest.json')) and not force:
        log(f'{tag}: already captured ({final}); --force to redo')
        return 'skipped'

    res_dir = estate.results
    inv_path = os.path.join(res_dir, f'{tag}-investigation.json')
    inj_path = os.path.join(res_dir, f'{tag}-inject.json')
    if not os.path.exists(inv_path):
        raise CaptureError(f'{tag}: no {os.path.basename(inv_path)}')
    run = load(inv_path)
    inv_id = (run.get('investigation') or {}).get('id')
    if not inv_id:
        raise CaptureError(f'{tag}: the investigation record has no id')

    # 1. The analysis, fresh from the API.
    inv = estate.api(f'/data/investigations/{inv_id}/')
    batch_id = inv.get('batch_id')
    if not batch_id:
        raise CaptureError(f'{tag}: investigation {inv_id} has no batch ({inv.get("status")})')
    analysis = {
        'investigation': inv,
        'batch': estate.api(f'/data/batches/{batch_id}/'),
        'issues': estate.api(f'/data/issues/{batch_id}/'),
        'timeline': estate.api(f'/data/batches/{batch_id}/timeline/'),
        'history': estate.api(f'/data/batches/{batch_id}/history/'),
    }

    # 4. The injection record.
    inject = load(inj_path) if os.path.exists(inj_path) else None
    revert_path = os.path.join(res_dir, f'{tag}-revert.json')
    revert = load(revert_path) if os.path.exists(revert_path) else None
    if inject is None:
        raise CaptureError(f'{tag}: no inject record; the capture needs to know when the fault started')

    # The window: SerOps' own window, widened to cover the fault from start to revert.
    margin = timedelta(minutes=int(estate.cfg.get('margin_minutes', DEFAULT_MARGIN_MINUTES)))
    asked = (parse_time(inv.get('window_start')), parse_time(inv.get('window_end')))
    fault_start = parse_time(inject.get('started'))
    fault_end = parse_time((revert or {}).get('at')) or asked[1]
    start = min(t for t in (asked[0], fault_start) if t) - margin
    end = max(t for t in (asked[1], fault_end) if t) + margin
    if end - start > timedelta(minutes=MAX_WINDOW_MINUTES):
        raise CaptureError(f'{tag}: window {iso(start)}..{iso(end)} is longer than {MAX_WINDOW_MINUTES} min')
    services = list(inv.get('services') or []) or list(estate.cfg.get('incident_services', {}).get(incident, []))
    if not services:
        raise CaptureError(f'{tag}: no services in the investigation nor in capture.json incident_services')

    injection = {'incident': incident, 'round': rnd, 'inject': inject, 'revert': revert,
                 'fault_started': iso(fault_start) if fault_start else None,
                 'fault_reverted': iso(fault_end) if revert else None,
                 'services': services, 'key': incident_key(estate, incident)}

    # 5. Versions.
    serops_version = estate.api('/version/')
    if not (serops_version or {}).get('git_sha'):
        raise CaptureError(f'{tag}: SerOps reports no commit (/api/version/ git_sha is empty); build the '
                           'images with --build-arg SEROPS_GIT_SHA')
    versions = {'serops': serops_version, 'estate_setup': setup_commit(estate),
                'model': model_in_use(estate, analysis['batch'], inv),
                'capture_tool_commit': subprocess.run(['git', '-C', HERE, 'rev-parse', 'HEAD'],
                                                      capture_output=True, text=True).stdout.strip()}

    # 2. The query trail.
    trail = fetch_trail(estate, access, [f'investigation-{inv_id}', batch_id])

    # 3. The stores, read directly.
    store_data, truncated = {}, {}
    for store in estate.cfg['stores']:
        fn = CAPTURERS.get(store['kind'])
        if fn is None:
            raise CaptureError(f"unknown store kind {store['kind']!r}")
        base = store_base(store, access)
        log(f"{tag}: reading {store['name']} ({store['kind']}) {iso(start)}..{iso(end)}")
        data, cut = fn(estate, store, base, services, start, end)
        data.update({'store': store['name'], 'window': {'start': iso(start), 'end': iso(end)}})
        store_data[store['name']] = data
        truncated[store['name']] = cut

    # Redact, check, write.
    redactor = Redactor()
    known = estate.secrets()
    parent = os.path.join(estate.output, estate.name)
    os.makedirs(parent, mode=0o700, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f'.{tag}.partial-', dir=parent)
    try:
        files = {}
        plan = [('analysis.json', analysis, False), ('injection.json', injection, False),
                ('versions.json', versions, False)]
        if trail is not None:
            plan.append(('query-trail.jsonl.gz', trail, True))
        plan += [(f'{name}.json.gz', data, True) for name, data in store_data.items()]
        for fname, obj, gz in plan:
            clean = redactor.walk(obj)
            path = os.path.join(tmp, fname)
            if fname.endswith('.jsonl.gz'):
                raw = ('\n'.join(json.dumps(e, default=str) for e in clean) + '\n').encode()
                with open(path, 'wb') as f, gzip.GzipFile(fileobj=f, mode='wb', mtime=0) as g:
                    g.write(raw)
            else:
                raw = write_json(path, clean, gz)
            hits = secret_hits(raw.decode('utf-8', 'replace'), known)
            if hits:
                raise SecretFound(f'{tag}: {fname} still holds {", ".join(sorted(set(hits)))} after '
                                  'redaction; nothing saved for this incident')
            files[fname] = {'bytes': os.path.getsize(path), 'uncompressed_bytes': len(raw),
                            'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest()}
        manifest = {
            'estate': estate.name, 'incident': incident, 'round': rnd,
            'captured_at': iso(datetime.now(timezone.utc)),
            'investigation_id': inv_id, 'batch_id': batch_id,
            'window': {'captured': {'start': iso(start), 'end': iso(end)},
                       'serops_asked': {'start': inv.get('window_start'), 'end': inv.get('window_end')}},
            'services': services,
            'query_trail': ({'requests': len(trail), 'stores': sorted({e.get('store') for e in trail})}
                            if trail is not None else 'not recorded (no "trail" in capture.json)'),
            'stores': {n: {'kind': d['kind'], 'truncated': truncated[n],
                           **{k: d[k] for k in ('series_count', 'metric_names', 'metric_types') if k in d},
                           **({'per_service': {s: {k: v for k, v in x.items()
                                                   if k in ('lines', 'documents', 'traces', 'truncated')}
                                               for s, x in d['services'].items()}} if 'services' in d else {})}
                       for n, d in store_data.items()},
            'redaction': {'tool': 'backend/Utils/data_redaction.py', 'findings': redactor.counts},
            'secret_scan': {'patterns': sorted(SECRET_PATTERNS), 'known_values_checked': len(known),
                            'result': 'clean'},
            'files': files,
            'total_bytes': sum(f['bytes'] for f in files.values()),
        }
        write_json(os.path.join(tmp, 'manifest.json'), manifest)
        if os.path.exists(final):
            shutil.rmtree(final)
        os.rename(tmp, final)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    log(f"{tag}: saved {final} ({manifest['total_bytes'] / 1e6:.1f} MB)")
    return final


def runs_in(results):
    tags = set()
    for name in os.listdir(results):
        m = re.match(r'(.+)-(r\d+)-investigation\.json$', name)
        if m and not m.group(1).startswith('BASELINE'):
            tags.add((m.group(1), m.group(2)))
    return sorted(tags)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('estate_dir')
    ap.add_argument('--only', nargs='*', help='incident-round tags, e.g. J2-r1')
    ap.add_argument('--force', action='store_true', help='capture again even when complete')
    args = ap.parse_args(argv)
    try:
        estate = Estate(args.estate_dir)
    except CaptureError as exc:
        log(f'error: {exc}')
        return 2
    runs = runs_in(estate.results)
    if args.only:
        runs = [r for r in runs if f'{r[0]}-{r[1]}' in set(args.only)]
    if not runs:
        log('error: no incident run to capture')
        return 2
    access = Access(estate.kubeconfig)
    failed = []
    try:
        for incident, rnd in runs:
            try:
                capture_incident(estate, access, incident, rnd, force=args.force)
            except SecretFound as exc:
                log(f'STOPPED at {incident}-{rnd}, secret scan: {exc}')
                log('Nothing was saved for this incident and the run stopped here. Find where the value '
                    'comes from, fix it, then capture again (the estate must still be up).')
                return 3
            except CaptureError as exc:
                log(f'FAILED {incident}-{rnd}: {exc}')
                failed.append(f'{incident}-{rnd}')
    finally:
        access.close()
    if failed:
        log(f'{len(failed)} of {len(runs)} not captured: {" ".join(failed)}')
        return 1
    log(f'{len(runs)} of {len(runs)} captured under {os.path.join(estate.output, estate.name)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
