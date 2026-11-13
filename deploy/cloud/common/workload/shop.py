"""Sample "shop" service for validating SerOps on a cluster. One file, standard library only.

The same code runs as three services, chosen by SERVICE:
  frontend  -> GET /       calls checkout
  checkout  -> GET /checkout  calls payments
  payments  -> GET /charge  uses a (simulated) database pool

What a real app would give an observability stack:
  * logs on stdout, one line each, level first ("2026-... ERROR payments ...")
    so Promtail ships them and SerOps reads the level from the line prefix;
  * Prometheus metrics on /metrics (requests by status, latency sum/count);
  * OpenTelemetry spans sent as OTLP/HTTP JSON to OTEL_ENDPOINT (the
    collector), with W3C traceparent propagated between services.

LOG_FORMAT (the "messy shop" group: each team logs its own way, see
run.sh phase_messy):
  plain  the line above (default)
  pino   Node's Pino: JSON, numeric levels (30 info, 40 warn, 50 error),
         base fields project/env set by the team (env spelled "prod")
  ecs    an ecs-logging library: JSON with flat dotted keys (log.level,
         service.name, service.environment); service and environment
         values from LOG_SERVICE_NAME / LOG_ENVIRONMENT
  otel   OpenTelemetry logs over OTLP/HTTP to OTEL_LOGS_ENDPOINT, with the
         resource attributes an SDK sets (service.name, service.namespace,
         deployment.environment.name); stdout keeps the plain line

Fault: payments reads DB_POOL_SIZE (default 20). Below 5 the pool runs dry
under the load generator's traffic: most charges fail with "pool exhausted"
and a 503, and checkout and frontend log the upstream failures. A "bad
deploy" in the suite is a rollout that sets DB_POOL_SIZE=2.
"""
import json, os, random, secrets, sys, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SERVICE = os.environ['SERVICE']
DOWNSTREAM = os.environ.get('DOWNSTREAM', '')
OTEL = os.environ.get('OTEL_ENDPOINT', '').rstrip('/')
POOL = int(os.environ.get('DB_POOL_SIZE', '20'))
VERSION = os.environ.get('VERSION', '1.0.0')
LOG_FORMAT = os.environ.get('LOG_FORMAT', 'plain')
LOG_SERVICE_NAME = os.environ.get('LOG_SERVICE_NAME', SERVICE)
LOG_ENVIRONMENT = os.environ.get('LOG_ENVIRONMENT', 'production')
OTEL_LOGS = os.environ.get('OTEL_LOGS_ENDPOINT', '').rstrip('/')
PINO_LEVELS = {'DEBUG': 20, 'INFO': 30, 'WARN': 40, 'ERROR': 50, 'FATAL': 60}
OTEL_SEVERITY = {'DEBUG': 5, 'INFO': 9, 'WARN': 13, 'ERROR': 17, 'FATAL': 21}

lock = threading.Lock()
counts = {}          # (path, code) -> n
latency = [0.0, 0]   # sum seconds, count
spans = []
in_use = 0


logs_out = []  # OTLP log records waiting for flush_logs


def log(level, msg):
    now = time.time()
    ts = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now)) + f'.{int(now * 1000) % 1000:03d}Z'
    if LOG_FORMAT == 'pino':
        print(json.dumps({'level': PINO_LEVELS.get(level, 30), 'time': int(now * 1000), 'pid': os.getpid(),
                          'hostname': os.environ.get('HOSTNAME', ''), 'name': SERVICE,
                          'project': 'shop', 'env': 'prod', 'msg': msg}), flush=True)
        return
    if LOG_FORMAT == 'ecs':
        print(json.dumps({'@timestamp': ts, 'log.level': level.lower(), 'message': msg,
                          'ecs.version': '1.6.0', 'service.name': LOG_SERVICE_NAME,
                          'service.environment': LOG_ENVIRONMENT, 'service.version': VERSION,
                          'project': 'shop', 'process.pid': os.getpid()}), flush=True)
        return
    print(f'{ts} {level} {SERVICE} {msg}', flush=True)
    if LOG_FORMAT == 'otel':
        with lock:
            logs_out.append({'timeUnixNano': str(int(now * 1e9)), 'severityText': level,
                             'severityNumber': OTEL_SEVERITY.get(level, 9), 'body': {'stringValue': msg}})


def flush_logs():
    while True:
        time.sleep(2)
        with lock:
            batch, logs_out[:] = logs_out[:], []
        if not batch or not OTEL_LOGS:
            continue
        body = {'resourceLogs': [{
            'resource': {'attributes': [
                {'key': 'service.name', 'value': {'stringValue': LOG_SERVICE_NAME}},
                {'key': 'service.namespace', 'value': {'stringValue': 'shop'}},
                {'key': 'service.version', 'value': {'stringValue': VERSION}},
                {'key': 'deployment.environment.name', 'value': {'stringValue': LOG_ENVIRONMENT}}]},
            'scopeLogs': [{'scope': {'name': 'shop'}, 'logRecords': batch}]}]}
        try:
            req = urllib.request.Request(OTEL_LOGS + '/v1/logs', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass  # collector not there yet: dropped, as a real SDK would


def span(trace_id, parent, name, start, end, ok, attrs):
    sid = secrets.token_hex(8)
    with lock:
        spans.append({
            'traceId': trace_id, 'spanId': sid, 'parentSpanId': parent or '', 'name': name, 'kind': 2,
            'startTimeUnixNano': str(int(start * 1e9)), 'endTimeUnixNano': str(int(end * 1e9)),
            'status': {'code': 1 if ok else 2},
            'attributes': [{'key': k, 'value': {'stringValue': str(v)}} for k, v in attrs.items()],
        })
    return sid


def flush_spans():
    while True:
        time.sleep(2)
        with lock:
            batch, spans[:] = spans[:], []
        if not batch or not OTEL:
            continue
        body = {'resourceSpans': [{
            'resource': {'attributes': [
                {'key': 'service.name', 'value': {'stringValue': SERVICE}},
                {'key': 'service.version', 'value': {'stringValue': VERSION}},
                {'key': 'deployment.environment', 'value': {'stringValue': 'production'}}]},
            'scopeSpans': [{'scope': {'name': 'shop'}, 'spans': batch}]}]}
        try:
            req = urllib.request.Request(OTEL + '/v1/traces', json.dumps(body).encode(),
                                         {'Content-Type': 'application/json'})
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass  # the collector may not be deployed yet; spans are dropped like a real SDK would


def call(path, trace_id, parent):
    req = urllib.request.Request(f'http://{DOWNSTREAM}{path}',
                                 headers={'traceparent': f'00-{trace_id}-{parent}-01'})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 504


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body, ctype='text/plain'):
        data = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        global in_use
        if self.path == '/metrics':
            return self.reply(200, metrics(), 'text/plain; version=0.0.4')
        if self.path == '/healthz':
            return self.reply(200, 'ok')
        tp = self.headers.get('traceparent', '').split('-')
        trace_id, parent = (tp[1], tp[2]) if len(tp) == 4 else (secrets.token_hex(16), None)
        start = time.time()
        sid = secrets.token_hex(8)
        if SERVICE == 'payments':
            with lock:
                ok = in_use < POOL
                if ok:
                    in_use += 1
            if ok:
                time.sleep(random.uniform(0.15, 0.3))  # a query; ~3-4 in flight at 15 rps
                with lock:
                    in_use -= 1
                code = 200
                log('INFO', f'GET /charge 200 {int((time.time() - start) * 1000)}ms trace_id={trace_id}')
            else:
                time.sleep(1.0)  # waited for a connection that never came
                code = 503
                log('ERROR', f'GET /charge 503 pool exhausted: timeout acquiring database connection '
                             f'(pool_size={POOL}, in_use={POOL}) trace_id={trace_id}')
        else:
            path = '/checkout' if SERVICE == 'frontend' else '/charge'
            code = call(path, trace_id, sid)
            code = 200 if code == 200 else 502
            ms = int((time.time() - start) * 1000)
            if code == 200:
                log('INFO', f'GET {self.path} 200 {ms}ms trace_id={trace_id}')
            else:
                log('ERROR', f'GET {self.path} 502 upstream {DOWNSTREAM.split(":")[0]} failed after {ms}ms '
                             f'trace_id={trace_id}')
        end = time.time()
        span(trace_id, parent, f'GET {self.path}', start, end, code == 200,
             {'http.method': 'GET', 'http.route': self.path, 'http.status_code': code})
        with lock:
            counts[(self.path, code)] = counts.get((self.path, code), 0) + 1
            latency[0] += end - start
            latency[1] += 1
        self.reply(code, 'ok' if code == 200 else 'error')


def metrics():
    with lock:
        lines = ['# TYPE http_requests_total counter']
        lines += [f'http_requests_total{{path="{p}",code="{c}"}} {n}' for (p, c), n in counts.items()]
        lines += ['# TYPE http_request_duration_seconds summary',
                  f'http_request_duration_seconds_sum {latency[0]:.3f}',
                  f'http_request_duration_seconds_count {latency[1]}',
                  '# TYPE db_pool_size gauge', f'db_pool_size {POOL if SERVICE == "payments" else 0}']
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    threading.Thread(target=flush_spans, daemon=True).start()
    threading.Thread(target=flush_logs, daemon=True).start()
    log('INFO', f'starting {SERVICE} {VERSION} (db_pool_size={POOL})' if SERVICE == 'payments'
        else f'starting {SERVICE} {VERSION}')
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
