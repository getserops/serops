#!/usr/bin/env python3
"""Turn real benchmark captures into demo seed files.

    python3 tools/demo-seed/build_seed.py --discover --captures DIR --runtime DIR --rename-map MAP
    python3 tools/demo-seed/build_seed.py --build    --captures DIR --runtime DIR --rename-map MAP \
                                          --out backend/Data/demo_seed --private-dir DIR
    python3 tools/demo-seed/build_seed.py --verify   --rename-map MAP --out backend/Data/demo_seed \
                                          [--private-dir DIR]

A capture (tools/estate-capture) holds one analysis exactly as SerOps made it.
This tool writes, per analysis, one ``<estate>-<incident>-<round>.json.gz``
with what a loader needs (batch, investigation, issues, traces, injection),
plus ``index.json``. It trims the logs but keeps every line the analysis
cites, renames what identifies the real estate, keeps every time as captured
and lists where the times are, and refuses to write when the result still
holds a real name or a secret. See README.md next to this file.

The rename map holds the real names: it lives outside the repository and
this tool never prints its values, only counts and paths.

Python 3.8+, standard library only.
"""
import argparse
import gzip
import hashlib
import ipaddress
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = 'serops-demo-seed/1'
MAX_LOG_LINES = 300
MAX_TRACES = 25
WINDOW_MARGIN_MINUTES = 15

ORG_NAME = 'Acme Cloud'
ORG_SLUG = 'acme-cloud'
MAIL_DOMAIN = 'acme.example'
# Invented people are role names, never something that could be a person's
# name. The private map may give a more telling one ('Fleet on-call').
PEOPLE = [('Team member %d' % n, 'team.member.%d' % n) for n in range(1, 11)]
AI_USAGE_REASON = 'not recorded in the capture; estate database deleted'


class SeedError(Exception):
    """The input cannot be converted, or the output failed a check."""


def log(msg):
    print(msg, flush=True)


def load_json(path):
    if path.endswith('.gz'):
        with gzip.open(path, 'rb') as f:
            return json.loads(f.read().decode('utf-8'))
    with open(path, 'rb') as f:
        return json.loads(f.read().decode('utf-8'))


def read_text(path):
    if path.endswith('.gz'):
        with gzip.open(path, 'rb') as f:
            return f.read().decode('utf-8', 'replace')
    with open(path, 'rb') as f:
        return f.read().decode('utf-8', 'replace')


def dump_bytes(obj, pretty=False):
    """The one serialisation: same object, same bytes."""
    if pretty:
        return (json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + '\n').encode('utf-8')
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def write_gz(path, data):
    with open(path, 'wb') as f:
        # No file name and mtime 0 in the header: the same content gives the same bytes.
        with gzip.GzipFile(filename='', fileobj=f, mode='wb', mtime=0, compresslevel=9) as g:
            g.write(data)


# --------------------------------------------------------------------------
# Time: find every time-bearing value, shift them all by one delta
# --------------------------------------------------------------------------

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
RX_ISO = re.compile(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})([T ])(\d{2}):(\d{2}):(\d{2})')
RX_HUMAN = re.compile(r'(?<!\d)(\d{1,2}) (%s) (\d{4}) (\d{2}):(\d{2}):(\d{2})' % '|'.join(MONTHS))
RX_SLASH = re.compile(r'(?<!\d)(\d{4})/(\d{2})/(\d{2}) (\d{2}):(\d{2}):(\d{2})')
RX_CLF = re.compile(r'(?<!\d)(\d{2})/(%s)/(\d{4}):(\d{2}):(\d{2}):(\d{2})' % '|'.join(MONTHS))
RX_COMPACT = re.compile(r'(?<=-batch-)(\d{14})(?=-)')
RX_DATE = re.compile(r'(?<![\d/.])(\d{4})([-.])(\d{2})\2(\d{2})(?![\d:T]|[-.]\d| \d{2}:)')
RX_DIGITS = re.compile(r'(?<![0-9A-Za-z.])(\d{19}|\d{16}|\d{13}|\d{10})(?![0-9A-Za-z])')
RX_CLOCK = re.compile(r'(?<![\d:.T-])(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?![\d:])')
RX_TIME_KEY = re.compile(r'(time|timestamp|_at$|^at$|^ts$|^start|^end|date|epoch|unix|since|until)', re.I)
EPOCH_UNITS = {10: ('s', 1), 13: ('ms', 10 ** 3), 16: ('us', 10 ** 6), 19: ('ns', 10 ** 9)}

TIME_FORMATS = {
    'iso': 'YYYY-MM-DD(T| )HH:MM:SS, any fraction and zone suffix kept; whole value or inside text',
    'human': 'D Mon YYYY HH:MM:SS inside text (Redis log style)',
    'slash': 'YYYY/MM/DD HH:MM:SS inside text',
    'clf': 'DD/Mon/YYYY:HH:MM:SS inside text',
    'compact': '%Y%m%d%H%M%S inside a batch id (<project>-batch-<time>-<hex>)',
    'date': 'YYYY-MM-DD or YYYY.MM.DD with no time of day (shift by the whole days of the delta)',
    'epoch_s_text': '10-digit epoch seconds as text or inside text',
    'epoch_ms_text': '13-digit epoch milliseconds as text or inside text or an id',
    'epoch_us_text': '16-digit epoch microseconds as text or inside text',
    'epoch_ns_text': '19-digit epoch nanoseconds as text or inside text or an id',
    'epoch_s_number': 'JSON number, epoch seconds',
    'epoch_ms_number': 'JSON number, epoch milliseconds',
    'epoch_us_number': 'JSON number, epoch microseconds',
    'epoch_ns_number': 'JSON number, epoch nanoseconds',
}


def parse_time(value):
    """ISO string -> aware datetime (UTC when no zone is given)."""
    text = str(value).strip().replace('Z', '+00:00')
    m = re.match(r'(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$', text)
    if m:
        text = '%s.%s%s' % (m.group(1), (m.group(2) + '000000')[:6], m.group(3))
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


class TimeContext:
    """What counts as a time of this analysis: within ``iso_days`` of the
    anchor for written dates, ``epoch_days`` for bare epoch numbers (a
    narrower range, so an ordinary number is not taken for a time)."""

    def __init__(self, anchor, iso_days=30, epoch_days=3):
        self.anchor = _naive(parse_time(anchor) if isinstance(anchor, str) else anchor)
        self.iso_lo = self.anchor - timedelta(days=iso_days)
        self.iso_hi = self.anchor + timedelta(days=iso_days)
        mid = (self.anchor - datetime(1970, 1, 1)).total_seconds()
        self.ep_lo = mid - epoch_days * 86400
        self.ep_hi = mid + epoch_days * 86400

    def near(self, dt):
        return self.iso_lo <= dt <= self.iso_hi

    def epoch_unit(self, number):
        """('s'|'ms'|'us'|'ns', multiplier) when the number is a time near the anchor."""
        for name, mult in EPOCH_UNITS.values():
            if self.ep_lo * mult <= number <= self.ep_hi * mult:
                return name, mult
        return None


def _dt(y, mo, d, h, mi, s):
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except ValueError:
        return None


def _string_times(text, ctx):
    """Every time written in ``text``: (start, end, format, datetime, rewrite)
    where ``rewrite(delta)`` gives the same span moved by ``delta``."""
    found = []

    def add(m, fmt, dt, rewrite):
        if dt is not None and ctx.near(dt):
            found.append((m.start(), m.end(), fmt, dt, rewrite))

    for m in RX_ISO.finditer(text):
        dt = _dt(*m.group(1, 2, 3, 5, 6, 7))
        add(m, 'iso', dt, lambda delta, dt=dt, sep=m.group(4): (dt + delta).strftime('%Y-%m-%d' + sep + '%H:%M:%S'))
    for m in RX_HUMAN.finditer(text):
        dt = _dt(m.group(3), MONTHS.index(m.group(2)) + 1, m.group(1), *m.group(4, 5, 6))
        pad = len(m.group(1)) == 2

        def human(delta, dt=dt, pad=pad):
            n = dt + delta
            return '%s %s %04d %s' % (('%02d' if pad else '%d') % n.day, MONTHS[n.month - 1], n.year,
                                      n.strftime('%H:%M:%S'))
        add(m, 'human', dt, human)
    for m in RX_SLASH.finditer(text):
        dt = _dt(*m.group(1, 2, 3, 4, 5, 6))
        add(m, 'slash', dt, lambda delta, dt=dt: (dt + delta).strftime('%Y/%m/%d %H:%M:%S'))
    for m in RX_CLF.finditer(text):
        dt = _dt(m.group(3), MONTHS.index(m.group(2)) + 1, m.group(1), *m.group(4, 5, 6))

        def clf(delta, dt=dt):
            n = dt + delta
            return '%02d/%s/%04d:%s' % (n.day, MONTHS[n.month - 1], n.year, n.strftime('%H:%M:%S'))
        add(m, 'clf', dt, clf)
    for m in RX_COMPACT.finditer(text):
        try:
            dt = datetime.strptime(m.group(1), '%Y%m%d%H%M%S')
        except ValueError:
            continue
        add(m, 'compact', dt, lambda delta, dt=dt: (dt + delta).strftime('%Y%m%d%H%M%S'))
    for m in RX_DATE.finditer(text):
        dt = _dt(m.group(1), m.group(3), m.group(4), 0, 0, 0)
        if dt is None:
            continue
        # A bare date stands for that day: move it by the delta's whole days.
        noon = dt + timedelta(hours=12)
        add(m, 'date', noon, lambda delta, dt=dt, sep=m.group(2):
            (dt + timedelta(days=delta.days)).strftime('%Y' + sep + '%m' + sep + '%d'))
    for m in RX_DIGITS.finditer(text):
        unit = ctx.epoch_unit(int(m.group(1)))
        if unit and EPOCH_UNITS[len(m.group(1))][0] == unit[0]:
            dt = datetime(1970, 1, 1) + timedelta(seconds=int(m.group(1)) / unit[1])
            found.append((m.start(), m.end(), 'epoch_%s_text' % unit[0], dt,
                          lambda delta, n=int(m.group(1)), mult=unit[1]: str(n + int(delta.total_seconds()) * mult)))
    found.sort(key=lambda f: (f[0], -f[1]))
    kept, last_end = [], -1
    for item in found:
        if item[0] >= last_end:
            kept.append(item)
            last_end = item[1]
    return kept


def _number_time(key, value, ctx):
    """(format, datetime, multiplier) when a JSON number is a time."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    unit = ctx.epoch_unit(value)
    if not unit:
        return None
    # Seconds are small enough to collide with ordinary figures (bytes,
    # counters): only a time-named key makes a 10-digit number a time.
    if unit[0] == 's' and not RX_TIME_KEY.search(str(key)):
        return None
    return 'epoch_%s_number' % unit[0], datetime(1970, 1, 1) + timedelta(seconds=value / unit[1]), unit[1]


def _esc(key):
    return str(key).replace('~', '~0').replace('/', '~1')


def walk_times(doc, ctx):
    """Yield (path, format, datetime) for every time-bearing value. Paths are
    JSON-pointer-like, list indices written ``*``; a time inside a dict key
    is reported at ``<path>/#key``."""
    def rec(obj, path, key):
        if isinstance(obj, dict):
            for k, v in obj.items():
                for _, _, fmt, dt, _ in _string_times(str(k), ctx):
                    yield path + '/#key', fmt, dt
                yield from rec(v, path + '/' + _esc(k), k)
        elif isinstance(obj, list):
            for v in obj:
                yield from rec(v, path + '/*', key)
        elif isinstance(obj, str):
            for _, _, fmt, dt, _ in _string_times(obj, ctx):
                yield path, fmt, dt
        else:
            hit = _number_time(key, obj, ctx)
            if hit:
                yield path, hit[0], hit[1]
    yield from rec(doc, '', '')


def find_time_paths(doc, anchor):
    """{path: sorted formats} of every time-bearing value of ``doc``."""
    paths = {}
    for path, fmt, _ in walk_times(doc, TimeContext(anchor)):
        paths.setdefault(path, set()).add(fmt)
    return {p: sorted(f) for p, f in sorted(paths.items())}


def find_clock_paths(doc, anchor):
    """Paths whose text holds a time of day with no date ("at 23:59:34"):
    they stay right only when the delta is a whole number of days."""
    ctx = TimeContext(anchor)
    paths = set()

    def rec(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                rec(v, path + '/' + _esc(k))
        elif isinstance(obj, list):
            for v in obj:
                rec(v, path + '/*')
        elif isinstance(obj, str) and ':' in obj:
            rest = obj
            for start, end, _, _, _ in reversed(_string_times(obj, ctx)):
                rest = rest[:start] + ' ' * (end - start) + rest[end:]
            rest = re.sub(r'(?<=\d{2}:\d{2}:\d{2})[.,]\d+', '', rest)
            if RX_CLOCK.search(rest):
                paths.add(path)
    rec(doc, '')
    return sorted(paths)


def shift_times(doc, delta_seconds, paths, anchor):
    """A copy of ``doc`` with every time at the listed ``paths`` moved by
    ``delta_seconds``. ``paths`` is ``{path: [formats]}`` as index.json lists
    them; ``anchor`` is the file's own (unshifted) anchor."""
    ctx = TimeContext(anchor)
    delta = timedelta(seconds=int(delta_seconds))

    def text(value, formats):
        out = value
        for start, end, fmt, _, rewrite in reversed(_string_times(value, ctx)):
            if fmt in formats:
                out = out[:start] + rewrite(delta) + out[end:]
        return out

    def rec(obj, path, key):
        if isinstance(obj, dict):
            key_formats = paths.get(path + '/#key')
            return {(text(k, key_formats) if key_formats and isinstance(k, str) else k):
                    rec(v, path + '/' + _esc(k), k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [rec(v, path + '/*', key) for v in obj]
        formats = paths.get(path)
        if not formats:
            return obj
        if isinstance(obj, str):
            return text(obj, formats)
        hit = _number_time(key, obj, ctx)
        if hit and hit[0] in formats:
            moved = int(delta.total_seconds()) * hit[2]
            return obj + (float(moved) if isinstance(obj, float) else moved)
        return obj
    return rec(doc, '', '')


def self_check_shift(doc, anchor, paths):
    """Shift far away and make sure nothing near the anchor is left."""
    moved = shift_times(doc, 1000 * 86400, paths, anchor)
    left = sorted({p for p, _, _ in walk_times(moved, TimeContext(anchor))})
    if left:
        raise SeedError('time shift is not complete at: ' + ', '.join(left[:10]))


# --------------------------------------------------------------------------
# Renaming
# --------------------------------------------------------------------------

RX_EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}')
RX_IP = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.]|-\d)')
RX_URL = re.compile(r'\b(?:https?|grpc|ssh|git)://([A-Za-z0-9._\-]+)(?::\d+)?(/[^\s"\'<>\\)]*)?')
ORG_KEYS = {'organisation_name', 'organization_name', 'organisation', 'organization'}
PERSON_KEYS = {'author', 'author_name', 'author_email', 'committer', 'committer_name', 'committer_email',
               'requested_by', 'resolved_by_name', 'pusher', 'sender', 'triggered_by', 'acknowledged_by_name'}
ALLOWED_NETS = [ipaddress.ip_network(n) for n in
                ('10.20.0.0/16', '10.99.0.0/16', '192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24',
                 '127.0.0.0/8', '0.0.0.0/32')]


def valid_ip(text):
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def ip_allowed(text):
    ip = valid_ip(text)
    return ip is not None and any(ip in net for net in ALLOWED_NETS)


def placeholder_ip(real, used=None, n=None):
    """A stable documentation-style address for a real one: RFC 1918
    (10.20.0.0/16) for private and link-local, RFC 5737 for the rest. With
    ``n`` (discovery order) the addresses are sequential; without, hashed."""
    ip = valid_ip(real)
    private = ip is not None and (ip.is_private or ip.is_link_local)
    if n is None:
        n = int(hashlib.sha256(real.encode()).hexdigest()[:6], 16)
        if private:
            return '10.99.%d.%d' % (n // 250 % 250 + 1, n % 250 + 1)
        return '%s.%d' % (('192.0.2', '198.51.100', '203.0.113')[n % 3], n // 3 % 250 + 1)
    if private:
        return '10.20.%d.%d' % (n // 250 % 250 + 1, n % 250 + 1)
    if n < 750:
        return '%s.%d' % (('203.0.113', '198.51.100', '192.0.2')[n // 250], n % 250 + 1)
    return placeholder_ip(real)


def empty_map():
    return {'version': 1, 'organisation': {}, 'cloud_project': {}, 'cluster': {}, 'host': {},
            'host_alias': {}, 'ip': {}, 'email': {}, 'repo': {}, 'repo_owner': {}, 'person': {},
            'person_alias': {}, 'third_party': {}, 'path_prefix': {}, 'url_host_keep': [],
            'kept_project_names': []}


class Renamer:
    """Applies the rename map to every string (keys too) of one estate's file."""

    def __init__(self, rmap, estate):
        self.map = rmap
        self.estate = estate
        self.counts = {}
        self.table = {}
        self.people = {}
        alternatives = []

        def add(real, replacement, category, bounded=False):
            if not real or real.lower() in self.table:
                return
            self.table[real.lower()] = (replacement, category)
            rx = re.escape(real)
            if bounded:
                rx = r'(?<![A-Za-z0-9])' + rx + r'(?![A-Za-z0-9])'
            alternatives.append((len(real), real.lower(), rx))

        kept = {n.lower() for n in rmap.get('kept_project_names') or []}
        for real in rmap.get('organisation', {}):
            # An organisation named like its project keeps that word as the
            # project name; only fields that name the organisation change.
            if real.lower() not in kept:
                add(real, ORG_NAME, 'organisation', bounded=True)
        for real, repl in rmap.get('repo', {}).items():
            add(real, repl.replace('{estate}', estate), 'repo')
        for cat in ('host', 'cloud_project', 'cluster', 'email'):
            for real, repl in rmap.get(cat, {}).items():
                add(real, repl, cat, bounded=(cat == 'cloud_project'))
        for real, repl in rmap.get('repo_owner', {}).items():
            add(real, repl, 'repo_owner', bounded=True)
        for real, repl in (rmap.get('host_alias', {}).get(estate) or {}).items():
            add(real, repl, 'host_alias', bounded=True)
        # Companies and domains that are not ours (a card brand in a log
        # line, the registry an image came from). Tools and open-source
        # project names are not listed there: they stay.
        for real, repl in rmap.get('third_party', {}).items():
            add(real, repl.replace('{estate}', estate), 'third_party', bounded=True)
        # A directory of the test setup in front of file paths (the folder the
        # estate's manifests sat in). Matched at the start of a path only.
        for real, repl in rmap.get('path_prefix', {}).items():
            if real and real.lower() not in self.table:
                self.table[real.lower()] = (repl, 'path_prefix')
                alternatives.append((len(real), real.lower(), r'(?<![A-Za-z0-9_.-])' + re.escape(real)))
        for real, person in rmap.get('person', {}).items():
            self.people[real.lower()] = person
            add(real, person['handle'] if ' ' not in real else person['name'], 'person',
                bounded=len(real) < 5)
        for real, owner in rmap.get('person_alias', {}).items():
            person = rmap['person'].get(owner)
            if person:
                add(real, person['handle'], 'person')
        alternatives.sort(key=lambda a: (-a[0], a[1]))
        self.rx = re.compile('|'.join(a[2] for a in alternatives), re.I) if alternatives else None
        self.ips = rmap.get('ip', {})
        self.orgs = {k.lower() for k in rmap.get('organisation', {})}

    def _count(self, category):
        self.counts[category] = self.counts.get(category, 0) + 1

    def _literal(self, m):
        repl, category = self.table[m.group(0).lower()]
        self._count(category)
        return repl

    def _email(self, m):
        addr = m.group(0)
        if addr.lower().endswith('@' + MAIL_DOMAIN):
            return addr
        self._count('email')
        local = addr.split('@', 1)[0].lower()
        person = self.people.get(local)
        if person:
            return person['email']
        if any(local == p['handle'] for p in self.people.values()):
            return '%s@%s' % (local, MAIL_DOMAIN)
        return 'user-%s@%s' % (hashlib.sha256(addr.lower().encode()).hexdigest()[:6], MAIL_DOMAIN)

    def _ip(self, m):
        addr = m.group(0)
        if valid_ip(addr) is None or ip_allowed(addr):
            return addr
        self._count('ip')
        return self.ips.get(addr) or placeholder_ip(addr)

    def text(self, value):
        person = self.people.get(value.strip().lower())
        if person:
            self._count('person')
            return person['name']
        out = self.rx.sub(self._literal, value) if self.rx else value
        if '@' in out:
            out = RX_EMAIL.sub(self._email, out)
        if '.' in out:
            out = RX_IP.sub(self._ip, out)
        return out

    def walk(self, obj, key=None):
        if isinstance(obj, str):
            if key in ORG_KEYS and obj.lower() in self.orgs:
                self._count('organisation')
                return ORG_NAME
            return self.text(obj)
        if isinstance(obj, dict):
            return {self.text(k) if isinstance(k, str) else k: self.walk(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.walk(v, key) for v in obj]
        return obj


# --------------------------------------------------------------------------
# Discovery of the rename map
# --------------------------------------------------------------------------

RX_D_ORG = re.compile(r'\\*"(?:organisation_name|organization_name)\\*"\s*:\s*\\*"([^"\\]{1,80})')
RX_D_PROJECT = re.compile(r'(?:\\*"project_id\\*"\s*:\s*\\*"|\bprojects/)([a-z][a-z0-9-]{4,28}[a-z0-9])')
RX_D_CLUSTER = re.compile(r'\\*"(?:cluster_name|cluster|k8s\.cluster\.name)\\*"\s*:\s*\\*"([^"\\]{1,80})')
RX_D_NODE = re.compile(r'(?<![A-Za-z0-9-])gke-([a-z0-9-]+?)-([a-z0-9]+-pool|pool-[a-z0-9]+|[a-z0-9]+)'
                       r'-([0-9a-f]{8})-([a-z0-9]{4})(?![A-Za-z0-9-])')
RX_D_HOST_SUFFIX = re.compile(r'\.(?:sslip\.io|nip\.io|internal)(?![A-Za-z0-9.-])')
RX_D_VM = re.compile(r'(?<![A-Za-z0-9-])gke-[0-9a-f]{20}[a-z0-9-]*')
HOST_CHARS = frozenset('abcdefghijklmnopqrstuvwxyz0123456789-.')
TOKEN_CHARS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._')


def widen(text, start, end, chars):
    """The whole token around text[start:end], made of ``chars``."""
    while start > 0 and text[start - 1] in chars:
        start -= 1
    while end < len(text) and text[end] in chars:
        end += 1
    return text[start:end]
RX_D_REPO = re.compile(r'(github\.com|gitlab\.com|bitbucket\.org)[/:]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)')
RX_D_GITHOST = re.compile(r'https?://([a-z0-9.-]*(?:gitea|gitlab|forgejo|gogs)[a-z0-9.-]*(?::\d+)?)'
                          r'/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)')
RX_D_URLHOST = re.compile(r'https?://([A-Za-z0-9.\-]+)')
REPO_SKIP_OWNERS = {'api', 'repos', 'orgs', 'users', 'v1', 'v3', 'v4', 'api-v1', 'login', 'settings'}
PUBLIC_TLD = re.compile(r'\.(?:com|org|net|io|dev|ai|app|cloud|co|sh|example)$')


def people_in(doc, found):
    """Names in commit author and requested_by fields: the only places a
    person is looked for."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k in PERSON_KEYS:
                if isinstance(v, str) and v.strip():
                    found.add(v.strip())
                elif isinstance(v, dict):
                    for name_key in ('name', 'username', 'email', 'login'):
                        if isinstance(v.get(name_key), str) and v[name_key].strip():
                            found.add(v[name_key].strip())
            people_in(v, found)
    elif isinstance(doc, list):
        for v in doc:
            people_in(v, found)


def discover(captures, runtime, selection, existing=None):
    """Scan every file of the selected captures and build the real ->
    replacement table. An existing map keeps its assignments."""
    rmap = empty_map()
    rmap.update(existing or {})
    for key, default in empty_map().items():
        rmap.setdefault(key, default)

    people, emails = set(), set()
    for estate, tag in selection:
        docs = [load_json(os.path.join(captures, estate, tag, name)) for name in ('analysis.json', 'injection.json')]
        rt = runtime_path(runtime, estate, tag)
        if rt and os.path.exists(rt):
            docs.append(load_json(rt))
        for doc in docs:
            people_in(doc, people)
    for value in sorted(people):
        m = re.search(r'<([^>]+@[^>]+)>', value)
        name = re.sub(r'\s*<[^>]*>', '', value).strip()
        if m:
            emails.add((m.group(1), name))
        if RX_EMAIL.fullmatch(name):
            emails.add((name, name.split('@')[0]))
            name = name.split('@')[0]
        if name and name.lower() not in {k.lower() for k in rmap['person']}:
            n = len(rmap['person'])
            if n >= len(PEOPLE):
                raise SeedError('more people than invented names: add names to PEOPLE')
            rmap['person'][name] = {'name': PEOPLE[n][0], 'handle': PEOPLE[n][1],
                                    'email': '%s@%s' % (PEOPLE[n][1], MAIL_DOMAIN)}
    for addr, owner in sorted(emails):
        person = next((p for k, p in rmap['person'].items() if k.lower() == owner.lower()), None)
        if person:
            rmap['email'].setdefault(addr, person['email'])
            rmap['person_alias'].setdefault(addr.split('@')[0], next(
                k for k in rmap['person'] if k.lower() == owner.lower()))
    handles = [k for k in rmap['person'] if ' ' not in k and len(k) >= 5]
    rx_alias = re.compile('|'.join(re.escape(h) for h in handles), re.I) if handles else None

    seen = {k: set() for k in ('organisation', 'cloud_project', 'cluster', 'host', 'ip', 'email', 'url_host')}
    nodes, repos, aliases = {}, set(), set()
    files = 0
    for estate, tag in selection:
        directory = os.path.join(captures, estate, tag)
        paths = [os.path.join(directory, n) for n in sorted(os.listdir(directory))]
        rt = runtime_path(runtime, estate, tag)
        if rt and os.path.exists(rt):
            paths.append(rt)
        for path in paths:
            text = read_text(path)
            files += 1
            seen['organisation'].update(RX_D_ORG.findall(text))
            seen['cloud_project'].update(RX_D_PROJECT.findall(text))
            seen['cluster'].update(RX_D_CLUSTER.findall(text))
            for m in RX_D_NODE.finditer(text):
                nodes.setdefault(estate, set()).add(m.group(0))
                seen['cluster'].add(m.group(1))
            for m in RX_D_HOST_SUFFIX.finditer(text):
                seen['host'].add(widen(text, m.start(), m.end(), HOST_CHARS).strip('.-'))
            seen['host'].update(RX_D_VM.findall(text))
            for m in RX_IP.finditer(text):
                if valid_ip(m.group(0)) is not None and not ip_allowed(m.group(0)):
                    seen['ip'].add(m.group(0))
            at = text.find('@')
            while at >= 0:
                m = RX_EMAIL.fullmatch(widen(text, at, at + 1, TOKEN_CHARS | {'%', '+'}).strip('.-_'))
                if m and not m.group(0).lower().endswith('@' + MAIL_DOMAIN) and not m.group(0).startswith('git@'):
                    seen['email'].add(m.group(0))
                at = text.find('@', at + 1)
            for m in RX_D_REPO.finditer(text):
                owner, repo = m.group(2), re.sub(r'\.git$', '', m.group(3))
                if owner.lower() not in REPO_SKIP_OWNERS:
                    repos.add((m.group(1), owner, repo))
            for m in RX_D_GITHOST.finditer(text):
                repos.add((m.group(1), m.group(2), re.sub(r'\.git$', '', m.group(3))))
            seen['url_host'].update(h.lower() for h in RX_D_URLHOST.findall(text))
            if rx_alias:
                for m in rx_alias.finditer(text):
                    aliases.add(widen(text, m.start(), m.end(), TOKEN_CHARS).strip('.-_'))

    rmap['kept_project_names'] = sorted(set(rmap.get('kept_project_names') or []) | {e for e, _ in selection})
    for real in sorted(seen['organisation']):
        rmap['organisation'].setdefault(real, ORG_NAME)
    for real in sorted(seen['cloud_project']):
        rmap['cloud_project'].setdefault(real, 'acme-prod-%d' % (len(rmap['cloud_project']) + 1))
    estates = sorted({e for e, _ in selection})
    for real in sorted(seen['cluster']):
        if real in rmap['cluster']:
            continue
        estate = next((e for e in estates if e in real.lower()), None)
        name = 'acme-%s-cluster' % estate if estate else 'acme-cluster-%d' % (len(rmap['cluster']) + 1)
        if name in rmap['cluster'].values():
            name = 'acme-cluster-%d' % (len(rmap['cluster']) + 1)
        rmap['cluster'][real] = name
    for estate in sorted(nodes):
        alias = rmap['host_alias'].setdefault(estate, {})
        for real in sorted(nodes[estate]):
            # The node pool's own name (instance group, templates) without the node suffix.
            rmap['host'].setdefault(real.rsplit('-', 1)[0], 'acme-%s-nodes' % estate)
            if real in rmap['host']:
                continue
            n = sum(1 for v in rmap['host'].values() if v.startswith('acme-%s-node-' % estate)) + 1
            rmap['host'][real] = 'acme-%s-node-%d' % (estate, n)
            alias.setdefault(real.rsplit('-', 1)[1], 'node-%d' % n)
    for real in sorted(seen['host']):
        if real not in rmap['host']:
            n = sum(1 for v in rmap['host'].values() if v.startswith('host-')) + 1
            rmap['host'][real] = 'host-%d.%s' % (n, MAIL_DOMAIN)
    for real in sorted(seen['host']):
        # A wildcard-DNS host name spells an address: that address is real too.
        m = re.match(r'(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})\.', real)
        if m and valid_ip('.'.join(m.groups())) is not None:
            seen['ip'].add('.'.join(m.groups()))
    for real in sorted(seen['ip'], key=lambda a: tuple(int(x) for x in a.split('.'))):
        if real not in rmap['ip']:
            rmap['ip'][real] = placeholder_ip(real, n=len(rmap['ip']))
    for real in sorted(seen['email']):
        if real not in rmap['email']:
            owner = next((p for k, p in rmap['person'].items() if k.lower() == real.split('@')[0].lower()), None)
            rmap['email'][real] = owner['email'] if owner else 'user-%d@%s' % (len(rmap['email']) + 1, MAIL_DOMAIN)
    owners = {}
    for host, owner, repo in sorted(repos):
        owners.setdefault((host, owner), set()).add(repo)
    # A repository is "ours" when its owner is a discovered person or it is
    # hosted on the estate's own git server; public third-party repositories
    # quoted in logs are left alone and reported by --verify.
    person_names = {k.lower() for k in rmap['person']} | {k.lower() for k in rmap['person_alias']}
    for (host, owner), names in sorted(owners.items()):
        own_host = host not in ('github.com', 'gitlab.com', 'bitbucket.org')
        if not own_host and owner.lower() not in person_names:
            continue
        for repo in sorted(names):
            rmap['repo'].setdefault('%s/%s/%s' % (host, owner, repo), 'git.%s/%s/{estate}' % (MAIL_DOMAIN, ORG_SLUG))
            rmap['repo'].setdefault('%s:%s/%s' % (host, owner, repo), 'git.%s/%s/{estate}' % (MAIL_DOMAIN, ORG_SLUG))
        if owner.lower() not in person_names:
            rmap['repo_owner'].setdefault(owner, ORG_SLUG)
        if own_host:
            rmap['host'].setdefault(host, 'git.%s' % MAIL_DOMAIN)
    for real in sorted(aliases):
        if real.lower() in person_names or RX_EMAIL.fullmatch(real):
            continue
        owner = next(h for h in handles if h.lower() in real.lower())
        rmap['person_alias'].setdefault(real, owner)
    renamed = {h.lower() for h in rmap['host']}
    keep = set(rmap['url_host_keep'])
    for host in sorted(seen['url_host']):
        if host in renamed or host in ('github.com', 'gitlab.com', 'bitbucket.org'):
            continue
        if PUBLIC_TLD.search(host) and not host.endswith(MAIL_DOMAIN):
            keep.add(host)
    rmap['url_host_keep'] = sorted(keep)
    return rmap, files


def map_counts(rmap):
    out = {k: len(v) for k, v in rmap.items() if isinstance(v, (dict, list)) and k != 'host_alias'}
    out.pop('kept_project_names', None)
    out['host_alias'] = sum(len(v) for v in rmap.get('host_alias', {}).values())
    return out


def real_values(rmap):
    """(category, real value, match rule) of everything that must not appear."""
    out = []
    kept = {n.lower() for n in rmap.get('kept_project_names') or []}
    for real in rmap.get('organisation', {}):
        if real.lower() not in kept:
            out.append(('organisation', real, 'bounded'))
    for cat in ('cloud_project', 'cluster', 'host', 'email', 'repo', 'repo_owner', 'person', 'person_alias'):
        for real in rmap.get(cat, {}):
            out.append((cat, real, 'bounded' if cat in ('repo_owner', 'cloud_project') or len(real) < 5 else 'plain'))
    for real in rmap.get('ip', {}):
        out.append(('ip', real, 'ip'))
    for estate, aliases in rmap.get('host_alias', {}).items():
        for real in aliases:
            out.append(('host_alias', real, 'bounded'))
    for real in rmap.get('third_party', {}):
        out.append(('third_party', real, 'bounded'))
    for real in rmap.get('path_prefix', {}):
        out.append(('path_prefix', real, 'plain'))
    return out


# --------------------------------------------------------------------------
# Evidence and the log trim
# --------------------------------------------------------------------------

RX_STAMP = re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?')
RX_LEAD = re.compile(r'^\s*\[([^\]]*)\]\s*')
RX_NOTE = re.compile(r'\s*(?:\[x\d+[^\]]*\]|\((?:repeated|x\d+|\d+ times)[^)]*\))\s*$', re.I)
RX_QUOTED = re.compile(r"'([^'\n]{12,200})'|\"([^\"\n]{12,200})\"")
LEVELS = {'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'CRITICAL', 'FATAL', 'TRACE', 'NOTICE'}


def log_source(line):
    return line.get('_source') if isinstance(line.get('_source'), dict) else line


def log_text(line):
    src = log_source(line)
    for key in ('message', 'log', 'Body.value', 'body', 'msg'):
        if isinstance(src.get(key), str) and src[key]:
            return src[key]
    return ''


def log_service(line):
    src = log_source(line)
    for key in ('service', 'service_name', 'service.name', 'svc', 'app'):
        if isinstance(src.get(key), str) and src[key]:
            return src[key]
    return ''


def _ms(value):
    """Epoch milliseconds of a written time, None when it is not one."""
    try:
        m = RX_STAMP.search(str(value))
        if not m:
            return None
        text = m.group(0).replace(' ', 'T').replace(',', '.')
        gap = parse_time(text) - datetime(1970, 1, 1, tzinfo=timezone.utc)
        return gap.days * 86400000 + gap.seconds * 1000 + gap.microseconds // 1000
    except (ValueError, OverflowError):
        return None


def log_ms(line):
    src = log_source(line)
    for key in ('@timestamp', 'timestamp', 'time'):
        if key in src:
            ms = _ms(src[key])
            if ms is not None:
                return ms
            if isinstance(src[key], (int, float)) and not isinstance(src[key], bool) and src[key] > 1e12:
                return int(src[key])
    return None


def _squash(text):
    return ' '.join(str(text).split()).lower()


def _fragments(text):
    return [f for f in (_squash(p) for p in re.split(r'\.\.\.|…', text)) if len(f) >= 6]


def _contains(haystack, fragments):
    pos = 0
    for frag in fragments:
        at = haystack.find(frag, pos)
        if at < 0:
            return False
        pos = at + len(frag)
    return bool(fragments)


def collect_evidence(analysis_results, issues, correlation_results, timeline, change_events):
    """Every reference the analysis makes to a log line.

    ``primary`` references are the analysis' own evidence (evidence_sources,
    occurrence timestamps); ``secondary`` ones are what the product derives
    or shows beside it (correlation samples, timeline, change events, text
    quoted in the issue fields)."""
    refs = []

    def ref(where, rank, **kw):
        kw.update(where=where, rank=rank)
        refs.append(kw)

    for a, result in enumerate(analysis_results):
        for i, issue in enumerate((result or {}).get('correlated_issues') or []):
            base = 'analysis_result[%d].correlated_issues[%d]' % (a, i)
            sources = issue.get('evidence_sources') or {}
            for n, text in enumerate(sources.get('logs') or []):
                if not isinstance(text, str):
                    continue
                stamps = [s for s in (_ms(m.group(0)) for m in RX_STAMP.finditer(text)) if s is not None]
                body, service = text, ''
                while True:
                    m = RX_LEAD.match(body)
                    if not m:
                        break
                    token = m.group(1).strip()
                    if token and not RX_STAMP.search(token) and token.upper() not in LEVELS and not service:
                        service = token
                    body = body[m.end():]
                body = RX_NOTE.sub('', body)
                ref('%s.evidence_sources.logs[%d]' % (base, n), 'primary', stamps=stamps, text=body,
                    service=service)
            for n, stamp in enumerate((issue.get('occurrences') or {}).get('timestamps') or []):
                ms = _ms(stamp)
                if ms is not None:
                    ref('%s.occurrences.timestamps[%d]' % (base, n), 'primary', stamps=[ms], text='', service='')
            if a == 0:
                for field in ('reasoning', 'root_cause', 'description', 'recommended_action'):
                    value = issue.get(field)
                    value = ' '.join(value) if isinstance(value, list) else (value or '')
                    for n, m in enumerate(RX_QUOTED.finditer(value)):
                        ref('%s.%s quote %d' % (base, field, n), 'quoted', stamps=[], text=m.group(1) or m.group(2),
                            service='')
    for i, issue in enumerate(issues or []):
        for field in ('reasoning', 'root_cause', 'description', 'recommendation'):
            for n, m in enumerate(RX_QUOTED.finditer(issue.get(field) or '')):
                ref('issues[%d].%s quote %d' % (i, field, n), 'quoted', stamps=[],
                    text=m.group(1) or m.group(2), service='')

    def samples(obj, path):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('sample_log_message', 'log_message', 'sample_message') and isinstance(v, str) and v.strip():
                    ref('correlation_results%s.%s' % (path, k), 'correlation', stamps=[], text=v,
                        service=str(obj.get('service') or ''), prefix=True)
                elif k in ('log_id', 'log_ids', 'sample_log_id'):
                    for n, value in enumerate(v if isinstance(v, list) else [v]):
                        ref('correlation_results%s.%s[%d]' % (path, k, n), 'primary', id=str(value), stamps=[],
                            text='', service='')
                else:
                    samples(v, '%s.%s' % (path, k))
        elif isinstance(obj, list):
            for n, v in enumerate(obj):
                samples(v, '%s[%d]' % (path, n))
    samples(correlation_results or {}, '')
    for n, event in enumerate((timeline or {}).get('events') or []):
        if event.get('kind') == 'log':
            ms = _ms(event.get('time'))
            ref('timeline.events[%d]' % n, 'timeline', stamps=[ms] if ms is not None else [],
                text=event.get('summary') or '', service=event.get('service') or '', prefix=True)
    for n, event in enumerate(change_events or []):
        ms = _ms(event.get('timestamp'))
        ref('change_events[%d]' % n, 'change_event', stamps=[ms] if ms is not None else [],
            text=event.get('message') or '', service=event.get('service') or '', prefix=True)
    return refs


def match_evidence(refs, logs, change_events=None):
    """Fill ``ref['lines']`` (indexes into ``logs``) and ``ref['located']``."""
    by_id, by_ms = {}, {}
    texts = []
    for n, line in enumerate(logs):
        if line.get('_id') is not None:
            by_id.setdefault(str(line['_id']), []).append(n)
        ms = log_ms(line)
        if ms is not None:
            by_ms.setdefault(ms, []).append(n)
        texts.append(_squash(log_text(line)))
    change_ms = {_ms(e.get('timestamp')) for e in change_events or []}
    change_text = [_squash(e.get('message') or '') for e in change_events or []]
    for ref in refs:
        lines = []
        if ref.get('id') is not None:
            lines = list(by_id.get(ref['id'], []))
        fragments = _fragments(ref.get('text') or '')
        if ref.get('prefix') and fragments:
            fragments = [fragments[0][:120]]
        if not lines:
            for ms in ref.get('stamps') or []:
                same = by_ms.get(ms, [])
                if len(same) > 1:
                    narrowed = [n for n in same if not ref.get('service') or log_service(logs[n]) == ref['service']]
                    same = narrowed or same
                    if fragments:
                        narrowed = [n for n in same if _contains(texts[n], fragments)]
                        same = narrowed or same
                lines.extend(same)
        if not lines and fragments:
            hits = [n for n, text in enumerate(texts) if _contains(text, fragments)]
            if hits:
                keyed = sorted(hits, key=lambda n: (log_ms(logs[n]) or 0, n))
                lines = [keyed[0]] if len(keyed) == 1 else [keyed[0], keyed[-1]]
        ref['lines'] = sorted(set(lines))
        ref['located'] = 'logs' if lines else ''
        if not lines and ref['rank'] != 'change_event':
            in_changes = any(ms in change_ms for ms in ref.get('stamps') or []) or (
                fragments and any(_contains(text, fragments) for text in change_text))
            if in_changes:
                ref['located'] = 'change_events'
    return refs


def spread(candidates, count):
    """``count`` items spread evenly over ``candidates`` (kept in order)."""
    if count <= 0 or not candidates:
        return []
    if count >= len(candidates):
        return list(candidates)
    if count == 1:
        return [candidates[len(candidates) // 2]]
    step = (len(candidates) - 1) / (count - 1)
    return [candidates[int(round(i * step))] for i in range(count)]


def trim_logs(logs, refs, max_lines=MAX_LOG_LINES):
    """At most ``max_lines`` lines, in their original order: every line cited
    as evidence, the first and the last of the window, then what the product
    shows beside the analysis, then an even sample of the rest. Cited lines
    are never dropped, even past the limit. Lines are not altered."""
    total = len(logs)
    order = sorted(range(total), key=lambda n: (log_ms(logs[n]) is None, log_ms(logs[n]) or 0, n))
    primary = set()
    for ref in refs:
        if ref['rank'] == 'primary':
            primary.update(ref['lines'])
    must = set(primary)
    if order:
        must.update((order[0], order[-1]))
    keep = set(must)
    if total <= max_lines:
        keep = set(range(total))
    else:
        for rank in ('correlation', 'timeline', 'change_event', 'quoted'):
            for ref in refs:
                if ref['rank'] != rank:
                    continue
                for n in ref['lines']:
                    if len(keep) < max_lines:
                        keep.add(n)
        room = max_lines - len(keep)
        keep.update(spread([n for n in order if n not in keep], room))
    kept = [logs[n] for n in range(total) if n in keep]
    prim = [r for r in refs if r['rank'] == 'primary']
    second = [r for r in refs if r['rank'] != 'primary']
    stats = {
        'logs_total': total,
        'logs_kept': len(kept),
        'max_lines': max_lines,
        'over_limit': len(kept) > max_lines,
        'first_and_last_kept': bool(order) and order[0] in keep and order[-1] in keep if order else True,
        'evidence_references': len(prim),
        'evidence_references_located_in_logs': sum(1 for r in prim if r['located'] == 'logs'),
        'evidence_references_located_in_change_events': sum(1 for r in prim if r['located'] == 'change_events'),
        'evidence_references_not_located': sorted(r['where'] for r in prim if not r['located']),
        'evidence_lines_found': len(primary),
        'evidence_lines_kept': len(primary & keep),
        'related_references': len(second),
        'related_references_located': sum(1 for r in second if r['located']),
        'related_lines_found': len({n for r in second for n in r['lines']}),
        'related_lines_kept': len({n for r in second for n in r['lines']} & keep),
    }
    return kept, stats


def trim_cicd(cicd_logs, cited, max_lines=MAX_LOG_LINES):
    total = len(cicd_logs or [])
    if total <= max_lines:
        return list(cicd_logs or []), {'cicd_logs_total': total, 'cicd_logs_kept': total}
    cited = [str(c).lower() for c in cited if c]
    keep = {0, total - 1}
    for n, row in enumerate(cicd_logs):
        blob = json.dumps(row, sort_keys=True).lower()
        if any(c in blob for c in cited):
            keep.add(n)
    keep.update(spread([n for n in range(total) if n not in keep], max_lines - len(keep)))
    return [cicd_logs[n] for n in range(total) if n in keep], {'cicd_logs_total': total, 'cicd_logs_kept': len(keep)}


# --------------------------------------------------------------------------
# One seed file
# --------------------------------------------------------------------------

# Serializer output the loader must not write: derived from other rows, or
# a database key of the estate that no longer exists.
BATCH_DROP = ('id', 'issues', 'analysis', 'metrics_summary', 'timing', 'investigation', 'project', 'deployment')
ISSUE_DROP = ('id', 'batch', 'batch_id_str', 'batch_timestamp', 'project', 'project_name', 'confidence_display',
              'issue_type_display', 'status_display', 'error_class_display', 'correlation_summary',
              'informed_by', 'resolved_by_name', 'related_traces')
INVESTIGATION_DROP = ('id', 'status_label', 'batch_id', 'issue_count')
ISSUE_STATE_FIELDS = ('created_at', 'last_seen_at', 'occurrence_count')


def runtime_path(runtime, estate, tag):
    """The one file read in the estates folder: the issue state right after
    the investigation. Nothing else there is opened."""
    if not runtime:
        return None
    return os.path.join(runtime, estate, 'results', '%s-investigation.json' % tag)


def issue_row(issue, estate, batch_id):
    row = {k: v for k, v in issue.items() if k not in ISSUE_DROP}
    row['capture_ref'] = '%s-issue-%s' % (estate, issue.get('id'))
    # Kept only when the issue hangs on another batch than this one.
    if issue.get('batch_id_str') and issue['batch_id_str'] != batch_id:
        row['attached_batch_id'] = issue['batch_id_str']
        row['attached_batch_timestamp'] = issue.get('batch_timestamp')
    return row


def cited_trace_ids(batch_data, timeline):
    ids = []

    def add(value):
        if isinstance(value, str) and value and value not in ids:
            ids.append(value)

    traces = batch_data.get('traces') or {}
    for row in (traces.get('top_slow') or []) + (traces.get('top_errors') or []):
        add(row.get('trace_id'))
    for issue in (batch_data.get('analysis_result') or {}).get('correlated_issues') or []:
        for value in (issue.get('evidence_sources') or {}).get('traces') or []:
            add(value)

    def rec(obj):
        if isinstance(obj, dict):
            add(obj.get('trace_id'))
            for v in obj.values():
                rec(v)
        elif isinstance(obj, list):
            for v in obj:
                rec(v)
    rec(batch_data.get('correlation_results') or {})
    rec((timeline or {}).get('events') or [])
    return ids


def trace_section(capture_dir, manifest, batch_data, timeline, window_end):
    cited = cited_trace_ids(batch_data, timeline)
    snapshot = batch_data.get('traces') or {}
    section = {'snapshot_source': snapshot.get('source') if isinstance(snapshot, dict) else None,
               'cited_trace_ids': cited, 'cited_found': [], 'cited_missing': list(cited), 'items': [],
               'available': False, 'store': None}
    stores = [n for n, s in (manifest.get('stores') or {}).items() if s.get('kind') in ('serops-traces', 'tempo', 'jaeger')]
    if not stores:
        if not snapshot:
            section['reason'] = 'the estate sent no traces: the analysis has no trace snapshot and the capture no trace store'
        else:
            section['reason'] = ('the analysis read traces from an external store (%s) that the capture could not '
                                 'save: no span rows exist for the trace ids it cites' % (snapshot.get('source') or 'unknown'))
        return section
    name = stores[0]
    store = load_json(os.path.join(capture_dir, name + '.json.gz'))
    if store.get('kind') != 'serops-traces':
        section['reason'] = 'trace store %s (%s) is not in SerOps row form; not converted' % (name, store.get('kind'))
        return section
    traces = {}
    for service in sorted(store.get('services') or {}):
        for item in store['services'][service].get('items') or []:
            if item.get('trace_id'):
                traces.setdefault(item['trace_id'], item)
    full = {t: t for t in traces}
    found = []
    for cid in cited:
        hit = full.get(cid) or next((t for t in sorted(traces) if t.startswith(cid)), None)
        if hit:
            found.append(cid)
    picked = []
    for c in found:
        hit = full.get(c) or next(t for t in sorted(traces) if t.startswith(c))
        if hit not in picked:
            picked.append(hit)
    rest = sorted((t for t in traces if t not in picked),
                  key=lambda t: (0 if traces[t].get('error_span_count') else 1, traces[t].get('start_time') or '', t))
    picked += rest[:max(0, MAX_TRACES - len(picked))]
    starts = sorted(t.get('start_time') or '' for t in traces.values())
    after = bool(starts) and bool(window_end) and parse_time(starts[0]) > parse_time(window_end)
    section.update({
        'available': bool(traces), 'store': name, 'store_window': store.get('window'),
        'store_truncated': bool((manifest['stores'][name]).get('truncated')),
        'store_trace_count': len(traces),
        'store_span_count': sum(t.get('span_count') or len(t.get('spans') or []) for t in traces.values()),
        'store_first_start': starts[0] if starts else None, 'store_last_start': starts[-1] if starts else None,
        'store_traces_all_after_window': after,
        'cited_found': found, 'cited_missing': [c for c in cited if c not in found],
        'items': [traces[t] for t in picked],
        'reason': ('rows come from the capture file %s.json.gz, which the capture tool capped per service; '
                   '%d of the %d trace ids the analysis cites are in it'
                   % (name, len(found), len(cited))),
    })
    return section


def build_seed(estate, tag, captures, runtime, rmap, max_lines=MAX_LOG_LINES):
    """(seed document, facts for index.json and the reports) for one analysis."""
    directory = os.path.join(captures, estate, tag)
    analysis = load_json(os.path.join(directory, 'analysis.json'))
    injection = load_json(os.path.join(directory, 'injection.json'))
    versions = load_json(os.path.join(directory, 'versions.json'))
    manifest = load_json(os.path.join(directory, 'manifest.json'))
    incident, rnd = tag.rsplit('-', 1)

    raw_batch = analysis['batch']
    batch = {k: v for k, v in raw_batch.items() if k not in BATCH_DROP}
    data = dict(batch.get('data') or {})
    batch['data'] = data
    history = (analysis.get('history') or {}).get('analysis_history') or []
    batch['analysis_history'] = history
    investigation = analysis.get('investigation') or {}
    timeline = analysis.get('timeline') or {}

    capture_issues = (analysis.get('issues') or {}).get('results') or []
    rt_file = runtime_path(runtime, estate, tag)
    if rt_file and os.path.exists(rt_file):
        run_issues = ((load_json(rt_file).get('issues') or {}).get('results')) or []
        issue_source = 'run time (results/%s-investigation.json)' % tag
    else:
        raise SeedError('%s %s: no run-time investigation file; the issues to load come from it' % (estate, tag))

    # Trim on the captured text, before any renaming, so evidence matches.
    results = [data.get('analysis_result') or {}]
    for entry in history:
        if (entry.get('analysis_result') or {}) not in results:
            results.append(entry.get('analysis_result') or {})
    refs = collect_evidence(results, run_issues + capture_issues, data.get('correlation_results'), timeline,
                            data.get('change_events'))
    logs = data.get('logs') or []
    match_evidence(refs, logs, data.get('change_events'))
    data['logs'], trim = trim_logs(logs, refs, max_lines)
    cited_cicd = []
    for result in results:
        for issue in result.get('correlated_issues') or []:
            sources = issue.get('evidence_sources') or {}
            cited_cicd += list(sources.get('cicd') or []) + list(sources.get('code') or [])
    data['cicd_logs'], cicd_stats = trim_cicd(data.get('cicd_logs') or [], cited_cicd, max_lines)
    trim.update(cicd_stats)

    batch_id = batch.get('batch_id')
    issues = [issue_row(i, estate, batch_id) for i in run_issues]
    at_capture = [issue_row(i, estate, batch_id) for i in capture_issues]
    differing = {}
    by_ref = {i['capture_ref']: i for i in at_capture}
    for issue in issues:
        other = by_ref.get(issue['capture_ref'])
        if other is None:
            differing[issue['capture_ref']] = ['(not in the capture)']
        else:
            fields = sorted(k for k in set(issue) | set(other) if issue.get(k) != other.get(k))
            if fields:
                differing[issue['capture_ref']] = fields
    for ref_ in by_ref:
        if ref_ not in {i['capture_ref'] for i in issues}:
            differing[ref_] = ['(not at run time)']

    inv = {k: v for k, v in investigation.items() if k not in INVESTIGATION_DROP}
    for key in ('project', 'environment', 'deployment', 'requested_by'):
        if isinstance(inv.get(key), dict):
            inv[key] = inv[key].get('name')

    healthy = not issues and not ((data.get('analysis_result') or {}).get('correlated_issues'))
    model = versions.get('model') or {}
    seed = {
        'schema': SCHEMA,
        'anchor': batch.get('timestamp'),
        'source': {
            'estate': estate, 'incident': incident, 'round': rnd, 'healthy_window': healthy,
            'captured_at': manifest.get('captured_at'),
            'capture_window': (manifest.get('window') or {}).get('captured'),
            'serops': versions.get('serops'),
            'estate_setup_commit': (versions.get('estate_setup') or {}).get('commit'),
            'capture_tool_commit': versions.get('capture_tool_commit'),
            'issues_from': issue_source,
        },
        'organisation': {'name': ORG_NAME, 'slug': ORG_SLUG},
        'project': {'name': estate.capitalize(), 'key': estate,
                    'environment': (investigation.get('environment') or {}).get('name')
                    if isinstance(investigation.get('environment'), dict) else investigation.get('environment'),
                    'repository': 'git.%s/%s/%s' % (MAIL_DOMAIN, ORG_SLUG, estate)},
        'model': {'used': model.get('model'), 'provider': model.get('provider'),
                  'batch_records': model.get('batch_records'), 'source': model.get('source'),
                  'settings_updated_at': model.get('settings_updated_at')},
        'ai_usage': None,
        'ai_usage_reason': AI_USAGE_REASON,
        'batch': batch,
        'trim': trim,
        'investigation': inv,
        'issues': issues,
        'traces': trace_section(directory, manifest, raw_batch.get('data') or {}, timeline,
                                investigation.get('window_end')),
        'injection': {
            'inject': injection.get('inject'), 'revert': injection.get('revert'),
            'fault_started': injection.get('fault_started'), 'fault_reverted': injection.get('fault_reverted'),
            'services': injection.get('services'),
            'pre_registered_key': {k: v for k, v in (injection.get('key') or {}).items() if k != 'file'} or None,
        },
        'derived_reference': {
            'note': 'computed by SerOps from the rows above at capture time; for comparison only, never written',
            'timeline_event_count': timeline.get('event_count'),
            'timeline_events_by_kind': _count_by((timeline.get('events') or []), 'kind'),
            'timeline_causal_pairs': len(timeline.get('causal_pairs') or []),
            'issue_summary': (analysis.get('issues') or {}).get('summary'),
        },
    }
    if differing:
        seed['issues_at_capture'] = at_capture

    renamer = Renamer(rmap, estate)
    seed = renamer.walk(seed)
    paths = find_time_paths(seed, seed['anchor'])
    self_check_shift(seed, seed['anchor'], paths)

    anchor = parse_time(seed['anchor'])
    issue_facts = []
    for issue in seed['issues']:
        created = issue.get('created_at')
        issue_facts.append({
            'capture_ref': issue['capture_ref'], 'severity': issue.get('severity'),
            'component': issue.get('component'), 'issue_type': issue.get('issue_type'),
            'status': issue.get('status'),
            'created_at': created, 'last_seen_at': issue.get('last_seen_at'),
            'occurrence_count': issue.get('occurrence_count'),
            'created_at_precedes_batch': bool(created) and parse_time(created) < anchor,
            'differs_from_capture': differing.get(issue['capture_ref'], []),
        })
    facts = {
        'estate': estate, 'incident': incident, 'round': rnd, 'healthy_window': healthy,
        'project': seed['project']['name'], 'anchor': seed['anchor'], 'batch_id': seed['batch'].get('batch_id'),
        'trigger': seed['batch'].get('trigger'), 'sentinel_decision': seed['batch'].get('sentinel_decision'),
        'model_used': seed['model']['used'], 'token_count': seed['batch'].get('token_count'),
        'trim': seed['trim'], 'issues': issue_facts,
        'issues_differ_from_capture': {k: v for k, v in sorted(differing.items())},
        'traces': {k: (len(v) if k in ('items', 'cited_trace_ids', 'cited_found', 'cited_missing') else v)
                   for k, v in seed['traces'].items() if k not in ('store_window',)},
        'time_paths': paths, 'clock_paths': find_clock_paths(seed, seed['anchor']),
        'renamed': dict(sorted(renamer.counts.items())),
    }
    return seed, facts


def _count_by(rows, key):
    out = {}
    for row in rows:
        out[str(row.get(key))] = out.get(str(row.get(key)), 0) + 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def secret_patterns():
    """The capture tool's own list, so both tools look for the same shapes."""
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', 'estate-capture')))
    try:
        import capture
        return dict(capture.SECRET_PATTERNS)
    finally:
        sys.path.pop(0)


def _real_rx(real, rule):
    rx = re.escape(real)
    if rule == 'bounded':
        rx = r'(?<![A-Za-z0-9])' + rx + r'(?![A-Za-z0-9])'
    elif rule == 'ip':
        rx = r'(?<![\d.])' + rx + r'(?![\d.])'
    return re.compile(rx, re.I)


def internal_labels(doc):
    """Namespaces, services and project names of a seed file: a host made of
    these is an in-cluster service of the (fictional) estate."""
    labels = {'svc', 'cluster', 'local', 'localhost'}
    keys = {'namespace', 'namespace_name', 'k8s.namespace.name', 'service.namespace', 'project_name',
            'service', 'service_name', 'service.name', 'component', 'svc', 'app'}

    def rec(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in keys and isinstance(v, str):
                    labels.add(v.lower())
                elif k in ('services', 'affected_services', 'services_touched') and isinstance(v, list):
                    labels.update(str(s).lower() for s in v)
                rec(v)
        elif isinstance(obj, list):
            for v in obj:
                rec(v)
    rec(doc)
    return labels


def url_host_status(host, path, labels, keep):
    host = host.lower().rstrip('.')
    if host == MAIL_DOMAIN or host.endswith('.' + MAIL_DOMAIN):
        return 'ok'
    if valid_ip(host) is not None:
        return 'ok' if ip_allowed(host) else 'bad'
    parts = host.split('.')
    if len(parts) == 1 or parts[-1] in labels or host.endswith('.svc') or host.endswith('.cluster.local'):
        return 'ok'
    if host in keep:
        return 'doubtful'
    return 'bad'


def check_time_window(seed):
    """Every time of the analysis must lie inside [window start - 15 min,
    capture time], except an issue's created_at that precedes its batch (the
    issue was first raised by an earlier batch). Returns {path: count}."""
    inv = seed.get('investigation') or {}
    if not inv.get('window_start') or not (seed.get('source') or {}).get('captured_at'):
        return {'(no window_start or captured_at)': 1}
    lo = _naive(parse_time(inv['window_start'])) - timedelta(minutes=WINDOW_MARGIN_MINUTES)
    hi = _naive(parse_time(seed['source']['captured_at'])) + timedelta(seconds=1)
    anchor = parse_time(seed['anchor'])
    exempt = set()
    for section in ('issues', 'issues_at_capture'):
        for issue in seed.get(section) or []:
            if issue.get('created_at') and parse_time(issue['created_at']) < anchor:
                exempt.add(section)
    scope = {k: seed[k] for k in ('batch', 'investigation', 'issues', 'issues_at_capture', 'traces', 'injection')
             if k in seed}
    scope['anchor'] = seed['anchor']
    bad = {}
    for path, fmt, dt in walk_times(scope, TimeContext(seed['anchor'])):
        if fmt == 'date':
            continue
        if lo <= dt <= hi:
            continue
        section = path.split('/')[1]
        if path == '/%s/*/created_at' % section and section in exempt and dt < _naive(anchor):
            continue
        bad[path] = bad.get(path, 0) + 1
    return bad


def verify_outputs(out_dir, rmap, patterns=None):
    """Check every output file. Returns (failures, doubtful, time_violations):
    failures are (file, check, count), with no value in them."""
    patterns = secret_patterns() if patterns is None else patterns
    reals = [(cat, real, _real_rx(real, rule)) for cat, real, rule in real_values(rmap)]
    keep = set(rmap.get('url_host_keep') or [])
    failures, doubtful, violations = [], [], {}
    names = sorted(n for n in os.listdir(out_dir) if n.endswith('.json.gz') or n == 'index.json')
    for name in names:
        path = os.path.join(out_dir, name)
        text = read_text(path)
        for cat, real, rx in reals:
            if rx.search(name):
                failures.append((name, 'real %s in the file name' % cat, 1))
            hits = len(rx.findall(text))
            if hits:
                failures.append((name, 'real %s value from the rename map' % cat, hits))
                doubtful.append((name, 'real %s value' % cat, real, hits))
        for kind, rx in sorted(patterns.items()):
            hits = len(rx.findall(text))
            if hits:
                failures.append((name, 'secret pattern: %s' % kind, hits))
        doc = json.loads(text)
        labels = internal_labels(doc)
        flat = _all_strings(doc)
        bad_ips, bad_mails, bad_hosts, kept_hosts = {}, {}, {}, {}
        for value in flat:
            if '.' in value:
                for m in RX_IP.finditer(value):
                    if valid_ip(m.group(0)) is not None and not ip_allowed(m.group(0)):
                        bad_ips[m.group(0)] = bad_ips.get(m.group(0), 0) + 1
            if '@' in value:
                for m in RX_EMAIL.finditer(value):
                    if not m.group(0).lower().endswith('@' + MAIL_DOMAIN):
                        bad_mails[m.group(0)] = bad_mails.get(m.group(0), 0) + 1
            if '://' in value:
                for m in RX_URL.finditer(value):
                    status = url_host_status(m.group(1), m.group(2), labels, keep)
                    if status == 'bad':
                        bad_hosts[m.group(1)] = bad_hosts.get(m.group(1), 0) + 1
                    elif status == 'doubtful':
                        kept_hosts[m.group(1)] = kept_hosts.get(m.group(1), 0) + 1
            # A repository named without a scheme ("github.com/owner/name").
            for m in RX_D_REPO.finditer(value):
                bad_hosts['%s/%s' % (m.group(1), m.group(2))] = bad_hosts.get('%s/%s' % (m.group(1), m.group(2)), 0) + 1
        for label, found in (('IP address outside the placeholder ranges', bad_ips),
                             ('e-mail address outside %s' % MAIL_DOMAIN, bad_mails),
                             ('URL host outside the allow-list', bad_hosts)):
            if found:
                failures.append((name, label, sum(found.values())))
                doubtful += [(name, label, value, count) for value, count in sorted(found.items())]
        doubtful += [(name, 'public URL host kept (listed in url_host_keep)', value, count)
                     for value, count in sorted(kept_hosts.items())]
        if name != 'index.json':
            if doc.get('ai_usage') is not None:
                failures.append((name, 'ai_usage is not null', 1))
            bad = check_time_window(doc)
            if bad:
                violations[name] = bad
    return failures, doubtful, violations


def _all_strings(doc):
    out = []

    def rec(obj):
        if isinstance(obj, str):
            out.append(obj)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                out.append(str(k))
                rec(v)
        elif isinstance(obj, list):
            for v in obj:
                rec(v)
    rec(doc)
    return out


def write_verify_report(private_dir, failures, doubtful, violations, files):
    if not private_dir:
        return None
    os.makedirs(private_dir, mode=0o700, exist_ok=True)
    path = os.path.join(private_dir, 'verify-report.md')
    lines = ['# Demo seed: verification report', '', 'Private. Holds real values when a check fails.', '',
             '%d files checked, %d failed checks, %d doubtful values, %d files with time-window violations.'
             % (files, len(failures), len(doubtful), len(violations)), '',
             '## Failed checks', '']
    lines += ['- `%s`: %s (%d)' % f for f in failures] or ['None.']
    lines += ['', '## Doubtful or offending values', '', '| File | What | Value | Count |', '|---|---|---|---|']
    lines += ['| %s | %s | `%s` | %d |' % d for d in doubtful] or ['| (none) | | | |']
    lines += ['', '## Times outside [window start - %d min, capture time]' % WINDOW_MARGIN_MINUTES, '',
              'An issue created_at that precedes its batch is exempt (index.json flags it). Counts and field '
              'paths only.', '']
    if violations:
        lines += ['| File | Field path | Count |', '|---|---|---|']
        for name in sorted(violations):
            lines += ['| %s | `%s` | %d |' % (name, p, c) for p, c in sorted(violations[name].items())]
    else:
        lines.append('None.')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return path


# --------------------------------------------------------------------------
# Private reports
# --------------------------------------------------------------------------

THIRD_PARTY = {
    'Google Cloud / GCP': r'google cloud|\bgcp\b|googleapis|\bgcr\.io|pkg\.dev', 'GKE': r'\bgke\b|gke-',
    'Kubernetes': r'kubernetes|\bk8s\b|kubelet|kubectl', 'Docker': r'docker', 'Helm': r'\bhelm\b',
    'Redis': r'redis', 'PostgreSQL': r'postgres(?:ql)?|\bpsql\b|psycopg', 'MySQL': r'mysql', 'MongoDB': r'mongo',
    'Elasticsearch': r'elasticsearch|\belastic\b', 'OpenSearch': r'opensearch', 'Loki': r'\bloki\b',
    'Prometheus': r'prometheus', 'VictoriaMetrics': r'victoria-?metrics', 'Grafana': r'grafana',
    'Jaeger': r'jaeger', 'Tempo': r'\btempo\b', 'OpenTelemetry': r'opentelemetry|\botel\b|\botlp\b',
    'Jenkins': r'jenkins', 'GitHub': r'github', 'GitLab': r'gitlab', 'Gitea': r'gitea', 'Flux': r'\bflux\b',
    'Argo CD': r'argo ?cd', 'Python': r'python', 'pip / PyPI': r'\bpip\b|pypi|pypa', 'Flask': r'flask',
    'Werkzeug': r'werkzeug', 'gunicorn': r'gunicorn', 'Node.js': r'node\.?js|\bnode:\d|"node"|\bnpm\b',
    'Java / JVM': r'\bjava\b|\bjvm\b|java\.lang', 'Eclipse Temurin': r'temurin|eclipse', 'Go': r'\bgolang\b',
    'gRPC': r'grpc', 'nginx': r'nginx', 'Envoy': r'envoy', 'Istio': r'istio', 'Cilium': r'cilium',
    'Kafka': r'kafka', 'RabbitMQ': r'rabbitmq', 'Linux': r'\blinux\b', 'Debian': r'debian', 'Alpine': r'alpine',
    'Ubuntu': r'ubuntu', 'AWS': r'\baws\b|amazon', 'Azure': r'azure', 'Stripe': r'stripe', 'Twilio': r'twilio',
    'Slack': r'\bslack\b', 'PagerDuty': r'pagerduty', 'Datadog': r'datadog', 'Sentry': r'\bsentry\b',
    'Online Boutique / microservices-demo (Google demo application)':
        r'online[- ]boutique|microservices-demo|hipster',
    'Claude (AI model)': r'claude', 'Anthropic': r'anthropic', 'OpenAI': r'openai|\bgpt-', 'Gemini': r'gemini',
    'cert-manager': r'cert-manager', 'Let\'s Encrypt': r'let\'?s ?encrypt', 'Visa / Mastercard': r'\bvisa\b|mastercard',
    'SQLAlchemy': r'sqlalchemy', 'Spring': r'spring ?boot|springframework', 'Tomcat': r'tomcat',
    'Jedis / Lettuce': r'jedis|lettuce', 'HikariCP': r'hikari', 'Celery': r'celery', 'Django': r'django',
    'Express': r'\bexpress\b', 'Chromium / Puppeteer': r'chromium|puppeteer', 'SMTP provider names': r'sendgrid|mailgun',
}
RX_IMAGE = re.compile(r'(?<![A-Za-z0-9./-])((?:[a-z0-9.-]+\.[a-z]{2,}(?::\d+)?/)?(?:[a-z0-9._-]+/)*[a-z0-9._-]+'
                      r'(?::[A-Za-z0-9._-]+|@sha256:[0-9a-f]{64}))(?![A-Za-z0-9])')
RX_SHA = re.compile(r'(?<![0-9a-f])[0-9a-f]{7,40}(?![0-9a-f])')
RX_MODULE = re.compile(r'(?<![A-Za-z0-9_.])([a-z][a-z0-9_]+)(?:\.[a-z][a-z0-9_]+)+\.[A-Z][A-Za-z]+')


def visible_text(seed):
    """(where, text) of what a user of the demo would read."""
    out = []
    batch = seed.get('batch') or {}
    data = batch.get('data') or {}
    out.append(('analysis text', batch.get('analysis_text') or ''))
    for s in _all_strings(data.get('analysis_result') or {}):
        out.append(('analysis result', s))
    for section in ('issues', 'issues_at_capture'):
        for issue in seed.get(section) or []:
            for s in _all_strings(issue):
                out.append(('issue fields', s))
    for line in data.get('logs') or []:
        out.append(('log line', log_text(line)))
        src = log_source(line)
        nested = src.get('kubernetes') if isinstance(src.get('kubernetes'), dict) else {}
        for holder in (src, nested):
            for key in ('container_image', 'image', 'container_hash'):
                if isinstance(holder.get(key), str):
                    out.append(('log labels (image)', holder[key]))
    for row in data.get('code_changes') or []:
        out.append(('commit message', row.get('message') or ''))
        for f in row.get('files') or []:
            out.append(('commit diff', '%s\n%s' % (f.get('path') or '', f.get('diff') or '')))
    for s in _all_strings(data.get('cicd_logs') or []):
        out.append(('CI/CD log', s))
    for s in _all_strings(data.get('change_events') or []):
        out.append(('change event', s))
    for s in _all_strings(data.get('correlation_results') or {}):
        out.append(('correlation', s))
    for s in _all_strings((data.get('metrics_summary') or {}).get('container_lifecycle') or {}):
        out.append(('container lifecycle', s))
    for s in _all_strings(seed.get('injection') or {}):
        out.append(('injection record', s))
    for s in _all_strings([t for t in (seed.get('traces') or {}).get('items') or []]):
        out.append(('trace spans', s))
    for s in _all_strings(seed.get('investigation') or {}):
        out.append(('investigation', s))
    out.append(('model', str((seed.get('model') or {}).get('used') or '')))
    return [(w, t) for w, t in out if t]


def third_party_report(seeds):
    names, images, hosts, shas, modules = {}, {}, {}, {}, {}
    compiled = {n: re.compile(rx, re.I) for n, rx in THIRD_PARTY.items()}
    for fname, seed in seeds:
        texts = visible_text(seed)
        for where, text in texts:
            for name, rx in compiled.items():
                hits = rx.findall(text)
                if hits:
                    m = rx.search(text)
                    entry = names.setdefault(name, {'count': 0, 'files': set(), 'where': set(), 'example': None})
                    entry['count'] += len(hits)
                    entry['files'].add(fname)
                    entry['where'].add(where)
                    if entry['example'] is None:
                        entry['example'] = ' '.join(text[max(0, m.start() - 50):m.end() + 50].split())
            if '/' in text or ':' in text:
                for m in RX_IMAGE.finditer(text):
                    ref = m.group(1)
                    if '/' in ref and where in ('log labels (image)', 'analysis result', 'issue fields',
                                                'container lifecycle', 'change event', 'commit diff'):
                        images.setdefault(ref, [0, fname])[0] += 1
            for m in RX_URL.finditer(text):
                url = m.group(0).split('?', 1)[0].rstrip('.,;:')
                hosts.setdefault(url if len(url) < 120 else url[:117] + '...', [0, fname, where])[0] += 1
            if where in ('log line', 'analysis result', 'issue fields', 'change event'):
                for m in RX_MODULE.finditer(text):
                    modules.setdefault(m.group(1), [0, m.group(0)])[0] += 1
        data = (seed.get('batch') or {}).get('data') or {}
        project = (seed.get('project') or {}).get('repository')

        def sha(value, where):
            if isinstance(value, str) and RX_SHA.fullmatch(value):
                shas.setdefault((value, project), [0, set()])
                shas[(value, project)][0] += 1
                shas[(value, project)][1].add(where)
        for row in data.get('code_changes') or []:
            sha(row.get('sha'), 'batch.data.code_changes')
        for row in data.get('cicd_logs') or []:
            sha(row.get('commit_sha'), 'batch.data.cicd_logs')
        for issue in (data.get('analysis_result') or {}).get('correlated_issues') or []:
            for value in (issue.get('caused_by_commits') or []) + ((issue.get('evidence_sources') or {}).get('code') or []):
                sha(value, 'analysis_result (caused_by_commits, evidence_sources.code)')
        for issue in seed.get('issues') or []:
            for row in issue.get('linked_commits') or []:
                sha(row.get('sha'), 'issues.linked_commits')
        for part in ('inject', 'revert'):
            for row in ((seed.get('injection') or {}).get(part) or {}).get('log') or []:
                for key in ('sha', 'built_sha', 'wait-run'):
                    sha(row.get(key), 'injection.%s.log' % part)
    lines = ['# Third-party names in the demo seed', '',
             'Private working note. Every third-party product, company or trademark name found in the converted, '
             'user-visible text (analysis text, issue fields, reasoning, recommendations, kept log lines, '
             'service and image names, commit messages and diffs, span attributes). Nothing was removed.', '',
             'Found by a fixed list of names (tools/demo-seed/build_seed.py, THIRD_PARTY), so a name that is not '
             'on the list is not counted here: the image, library and URL tables below catch those.', '',
             'The service names themselves are kept as captured. Those of the Shopfront project (adservice, '
             'cartservice, checkoutservice, currencyservice, emailservice, frontend, loadgenerator, paymentservice, '
             'productcatalogservice, recommendationservice, redis-cart, shippingservice) are the service names of '
             'the public demo application whose images are listed below.', '',
             '| Name | Count | Files | Where | Example |', '|---|---|---|---|---|']
    for name in sorted(names, key=lambda n: (-names[n]['count'], n)):
        e = names[name]
        lines.append('| %s | %d | %d | %s | `%s` |' % (name, e['count'], len(e['files']), ', '.join(sorted(e['where'])),
                                                      (e['example'] or '').replace('|', '\\|').replace('`', "'")[:160]))
    lines += ['', '## Container images named', '', '| Image | Count | First file |', '|---|---|---|']
    lines += ['| `%s` | %d | %s |' % (ref, v[0], v[1]) for ref, v in sorted(images.items())] or ['| (none) | | |']
    lines += ['', '## Libraries and runtimes named in error text', '',
              'Top-level package of every dotted class name in the log lines and the analysis (for example an '
              'exception class).', '', '| Package | Count | Example |', '|---|---|---|']
    lines += ['| `%s` | %d | `%s` |' % (name, v[0], v[1]) for name, v in sorted(modules.items())] or ['| (none) | | |']
    lines += ['', '## Commit shas the UI could render as links', '',
              'None resolves: the repositories were private test repositories, and they are renamed to '
              '`git.%s/%s/<estate>`, which does not exist. Render as plain text.' % (MAIL_DOMAIN, ORG_SLUG), '',
              '| Sha | Repository after renaming | Occurrences | Fields | Resolves |', '|---|---|---|---|---|']
    lines += ['| `%s` | %s | %d | %s | no |' % (k[0], k[1], v[0], ', '.join(sorted(v[1])))
              for k, v in sorted(shas.items())] or ['| (none) | | | | |']
    lines += ['', '## URLs in the text', '',
              'In-cluster service addresses of the estates and public documentation hosts quoted in log lines. '
              'None is a link the demo should follow. Query strings are left out.', '',
              '| URL | Count | First file | Where | Resolves |', '|---|---|---|---|---|']
    lines += ['| `%s` | %d | %s | %s | no (in-cluster or fictional host)%s |'
              % (url.replace('|', '%7C'), v[0], v[1], v[2],
                 '' if not PUBLIC_TLD.search(re.sub(r'^[a-z]+://([^/:]+).*$', r'\1', url)) else
                 '; public host, would resolve')
              for url, v in sorted(hosts.items())] or ['| (none) | | | | |']
    return '\n'.join(lines) + '\n', {n: names[n]['count'] for n in names}


def _fmt_step(row):
    return '`%s`' % json.dumps(row, sort_keys=True, ensure_ascii=False).replace('|', '\\|').replace('`', "'")


def resolution_facts(seeds):
    lines = ['# Resolution facts', '',
             'Private working note. Plain facts per incident analysis, from the injection record and the '
             'analysis. All times UTC. Steps are quoted as recorded.', '']
    for fname, seed in seeds:
        src = seed['source']
        if src.get('healthy_window'):
            continue
        inj = seed.get('injection') or {}
        inject, revert = inj.get('inject') or {}, inj.get('revert') or {}
        lines += ['## %s %s %s (`%s`)' % (seed['project']['name'], src['incident'], src['round'], fname), '']
        key = (inj.get('pre_registered_key') or {}).get('row')
        if key:
            lines += ['- Pre-registered injection row: %s' % key.replace('|', '\\|'), '']
        lines += ['**What was changed**', '',
                  '- Inject started: %s' % inject.get('started'), '- Inject finished: %s' % inject.get('at'),
                  '- Steps, in order:']
        lines += ['  %d. %s' % (n + 1, _fmt_step(row)) for n, row in enumerate(inject.get('log') or [])]
        lines += ['', '**What ended it**', '']
        if revert:
            lines += ['- Revert started: %s' % revert.get('started'), '- Revert finished: %s' % revert.get('at'),
                      '- Steps, in order:']
            lines += ['  %d. %s' % (n + 1, _fmt_step(row)) for n, row in enumerate(revert.get('log') or [])]
        else:
            lines += ['- No revert record in the capture.']
        lines += ['', '**Duration**', '',
                  '- Fault started (capture): %s' % inj.get('fault_started'),
                  '- Fault reverted (capture): %s' % inj.get('fault_reverted')]
        if inj.get('fault_started') and inj.get('fault_reverted'):
            secs = int((parse_time(inj['fault_reverted']) - parse_time(inj['fault_started'])).total_seconds())
            lines.append('- Lasted: %d min %02d s (%d s)' % (secs // 60, secs % 60, secs))
        inv = seed.get('investigation') or {}
        lines += ['- Investigation window: %s to %s' % (inv.get('window_start'), inv.get('window_end')),
                  '- Analysis finished: %s' % seed['batch'].get('analyzed_at'), '',
                  '**Issues the analysis raised** (state right after the investigation)', '']
        for issue in seed.get('issues') or []:
            lines.append('- %s, component `%s`, type %s, scope %s, confidence %s, error class %s, status %s; '
                         'created_at %s, last_seen_at %s, occurrence_count %s'
                         % (issue.get('severity'), issue.get('component'), issue.get('issue_type'),
                            issue.get('scope'), issue.get('confidence'), issue.get('error_class'),
                            issue.get('status'), issue.get('created_at'), issue.get('last_seen_at'),
                            issue.get('occurrence_count')))
            commits = [c.get('sha') for c in issue.get('linked_commits') or []]
            if commits:
                lines.append('  - Linked commits: %s' % ', '.join('`%s`' % c for c in commits))
        if not seed.get('issues'):
            lines.append('- None.')
        lines.append('')
    return '\n'.join(lines)


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def build_all(captures, runtime, rmap, out_dir, private_dir, selection, max_lines=MAX_LOG_LINES):
    """Convert, verify in a scratch directory, and only then put the files in
    place. Returns (exit code, summary rows)."""
    work = tempfile.mkdtemp(prefix='demo-seed-')
    try:
        index_files, seeds, all_paths, clock_paths = [], [], {}, set()
        for estate, tag in selection:
            seed, facts = build_seed(estate, tag, captures, runtime, rmap, max_lines)
            name = '%s-%s.json.gz' % (estate, tag)
            data = dump_bytes(seed)
            write_gz(os.path.join(work, name), data)
            with open(os.path.join(work, name), 'rb') as f:
                blob = f.read()
            for path, formats in facts.pop('time_paths').items():
                all_paths.setdefault(path, set()).update(formats)
            clock_paths.update(facts.pop('clock_paths'))
            facts.update({'file': name, 'bytes': len(blob), 'uncompressed_bytes': len(data),
                          'sha256': hashlib.sha256(blob).hexdigest()})
            index_files.append(facts)
            seeds.append((name, seed))
        index = {
            'schema': SCHEMA,
            'organisation': {'name': ORG_NAME, 'slug': ORG_SLUG},
            'max_log_lines': max_lines,
            'ai_usage': {'value': None, 'reason': AI_USAGE_REASON,
                         'note': 'batch.token_count is SerOps\' own size estimate of the batch text '
                                 '(characters / 4), not model usage: no cost may be computed from it'},
            'files': index_files,
            'time': {
                'anchor': 'each file\'s "anchor" is its batch timestamp; no time in any file was shifted',
                'how_to_shift': 'delta = wanted anchor - file anchor; move every value at the paths below by '
                                'that one delta (build_seed.shift_times does it and keeps each format)',
                'delta_rule': 'use a whole number of days: the texts at clock_time_only_paths name times of day '
                              'with no date ("at 23:59:34"), which only stay true for a whole-day delta',
                'path_syntax': 'JSON pointer from the file root; * is any list index; ~1 is a / inside a key; '
                               '/#key means the time is inside the dict keys at that path',
                'formats': TIME_FORMATS,
                'paths': {p: sorted(f) for p, f in sorted(all_paths.items())},
                'clock_time_only_paths': sorted(clock_paths),
            },
        }
        with open(os.path.join(work, 'index.json'), 'wb') as f:
            f.write(dump_bytes(index, pretty=True))

        failures, doubtful, violations = verify_outputs(work, rmap)
        report = write_verify_report(private_dir, failures, doubtful, violations, len(index_files) + 1)
        if failures:
            for name, check, count in failures:
                log('FAILED %s: %s (%d)' % (name, check, count))
            log('verification failed: nothing written to %s%s' % (out_dir, ('; details in ' + report) if report else ''))
            return 3, index_files
        os.makedirs(out_dir, exist_ok=True)
        for old in os.listdir(out_dir):
            if old.endswith('.json.gz') or old == 'index.json':
                os.remove(os.path.join(out_dir, old))
        for name in sorted(os.listdir(work)):
            shutil.copyfile(os.path.join(work, name), os.path.join(out_dir, name))
        if private_dir:
            text, _ = third_party_report(seeds)
            with open(os.path.join(private_dir, 'third-party-names.md'), 'w', encoding='utf-8') as f:
                f.write(text)
            with open(os.path.join(private_dir, 'resolution-facts.md'), 'w', encoding='utf-8') as f:
                f.write(resolution_facts(seeds))
        log('verification passed: %d doubtful values, %d files with time-window violations%s'
            % (len(doubtful), len(violations), ('; see ' + report) if report else ''))
        return 0, index_files
    finally:
        shutil.rmtree(work, ignore_errors=True)


def load_selection(path):
    doc = load_json(path)
    return [(estate, tag) for estate in doc for tag in doc[estate]]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--discover', action='store_true', help='scan the captures and write the rename map')
    mode.add_argument('--build', action='store_true', help='convert, verify, write (the default)')
    mode.add_argument('--verify', action='store_true', help='check the files already in --out')
    ap.add_argument('--captures', help='benchmark-captures directory (read only)')
    ap.add_argument('--runtime', help='estates directory; only <estate>/results/<tag>-investigation.json is read')
    ap.add_argument('--rename-map', required=True, help='private rename map (JSON), outside the repository')
    ap.add_argument('--out', default=os.path.normpath(os.path.join(HERE, '..', '..', 'backend', 'Data', 'demo_seed')))
    ap.add_argument('--private-dir', help='where the private reports go (outside the repository)')
    ap.add_argument('--selection', default=os.path.join(HERE, 'selection.json'))
    ap.add_argument('--max-log-lines', type=int, default=MAX_LOG_LINES)
    args = ap.parse_args(argv)
    repo = os.path.normpath(os.path.join(HERE, '..', '..'))
    for label, path in (('--rename-map', args.rename_map), ('--private-dir', args.private_dir)):
        if path and (os.path.abspath(path) + os.sep).startswith(repo + os.sep):
            log('error: %s must be outside the repository' % label)
            return 2
    try:
        if args.verify:
            rmap = load_json(args.rename_map)
            failures, doubtful, violations = verify_outputs(args.out, rmap)
            files = len([n for n in os.listdir(args.out) if n.endswith('.json.gz') or n == 'index.json'])
            report = write_verify_report(args.private_dir, failures, doubtful, violations, files)
            for name, check, count in failures:
                log('FAILED %s: %s (%d)' % (name, check, count))
            log('%d files checked: %d failed checks, %d doubtful values, %d time-window violations in %d files%s'
                % (files, len(failures), len(doubtful), sum(sum(v.values()) for v in violations.values()),
                   len(violations), ('; report: ' + report) if report else ''))
            return 3 if failures else 0
        if not args.captures:
            log('error: --captures is required')
            return 2
        selection = load_selection(args.selection)
        if args.discover:
            existing = load_json(args.rename_map) if os.path.exists(args.rename_map) else None
            rmap, files = discover(args.captures, args.runtime, selection, existing)
            os.makedirs(os.path.dirname(os.path.abspath(args.rename_map)), mode=0o700, exist_ok=True)
            fd = os.open(args.rename_map, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(dump_bytes(rmap, pretty=True))
            log('%d files scanned; rename map written to %s' % (files, args.rename_map))
            log('entries by category: ' + ', '.join('%s %d' % kv for kv in sorted(map_counts(rmap).items())))
            return 0
        rmap = load_json(args.rename_map)
        code, rows = build_all(args.captures, args.runtime, rmap, args.out, args.private_dir, selection,
                               args.max_log_lines)
        for row in rows:
            t = row['trim']
            log('%s: logs %d of %d, evidence lines %d found %d kept, %d of %d references located, issues %d, '
                'trace rows %d, %d bytes'
                % (row['file'], t['logs_kept'], t['logs_total'], t['evidence_lines_found'], t['evidence_lines_kept'],
                   t['evidence_references'] - len(t['evidence_references_not_located']), t['evidence_references'],
                   len(row['issues']), row['traces']['items'], row['bytes']))
        if code == 0:
            log('%d files and index.json written to %s' % (len(rows), args.out))
        return code
    except SeedError as exc:
        log('error: %s' % exc)
        return 2


if __name__ == '__main__':
    sys.exit(main())
