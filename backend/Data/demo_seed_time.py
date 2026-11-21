"""
Time shifting for the demo seed files (``Data/demo_seed/``).

Every seed file holds its times as captured. ``seed_demo_org`` places the
analyses on a recent date by moving every time-bearing value by one delta:
``shift_times(doc, delta_seconds, paths, anchor)``, where ``paths`` is the
``time.paths`` table of ``demo_seed/index.json``.

This is the time section of ``tools/demo-seed/build_seed.py``, kept the same
line for line: the converter is not shipped with the backend, and the two
must agree on what a time is. ``tools/demo-seed/test_shift_parity.py`` fails
when they differ. Standard library only.
"""

import re
from datetime import datetime, timedelta, timezone

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
