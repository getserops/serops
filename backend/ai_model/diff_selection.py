"""
Pick the parts of a batch's code diffs that the AI should actually read.

The prompt used to send the first 500 characters of each changed file. A
bug on line 140 of a 300-line diff was never seen, and an unrelated file
got the same space as the one the stack trace points at.

This module reads the stack frames in the batch's logs, ranks changed
files by whether a frame points at them, and sends whole diff hunks
around those lines and functions, inside a fixed character budget.
Files nothing points at still get a short excerpt, so a code-only bug
(no runtime evidence yet) stays visible.

Only diffs inside the incident window are ever read: SerOps never
fetches the rest of the repository. Diff excerpts and commit messages go
through the same secret/PII redaction as logs before they reach the
prompt; if redaction fails, the diff text is left out (fail closed).
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field
from typing import Iterable

# Character budgets. Roughly 4 characters per token, so the whole section
# stays under ~3k tokens however many commits the window holds.
TOTAL_BUDGET = 12_000
MATCHED_FILE_BUDGET = 3_500
UNMATCHED_FILE_BUDGET = 400
MAX_COMMITS = 10
MAX_FILES_LISTED = 8
# Lines kept either side of a frame's line when one hunk is too big.
LINE_WINDOW = 15
# A frame's line counts as "in" a hunk this many lines outside it.
LINE_SLACK = 10


@dataclass(frozen=True)
class StackRef:
    """One stack frame from the logs: a file, and where available a line
    and a function."""
    path: str
    line: int | None = None
    func: str | None = None


# One pattern per stack format. Each names ``path`` and, where the format
# has them, ``line`` and ``func``.
_FRAME_PATTERNS = [
    # Python:  File "/app/api/payments.py", line 42, in handle
    re.compile(r'File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>[\w<>.]+))?'),
    # C#:  at Acme.Pay.Retry.Run() in /src/Pay/Retry.cs:line 42
    re.compile(r'at (?P<func>[\w.<>`]+)\([^)]*\) in (?P<path>[^\s:]+\.cs):line (?P<line>\d+)'),
    # Java / Kotlin / Scala:  at com.acme.pay.Retry.run(Retry.java:42)
    re.compile(r'at (?P<func>[\w$.]+)\((?P<path>[\w$-]+\.(?:java|kt|scala|groovy)):(?P<line>\d+)\)'),
    # JS / TS:  at handle (/app/src/pay.ts:12:5)   or   at /app/src/pay.js:12:5
    re.compile(
        r'at (?:(?P<func>[\w$.<>\[\]]+) \()?(?:file://)?'
        r'(?P<path>[^\s():]+\.(?:js|jsx|ts|tsx|mjs|cjs)):(?P<line>\d+)(?::\d+)?\)?'
    ),
    # Ruby:  app/models/order.rb:42:in `charge'
    re.compile(r"(?P<path>[\w./-]+\.rb):(?P<line>\d+):in [`'](?P<func>[^'`]+)'"),
    # PHP:  #0 /var/www/src/Pay.php(42): Pay->run()   or   in /x/Pay.php on line 42
    re.compile(r'(?P<path>[\w./-]+\.php)\((?P<line>\d+)\)(?::\s*(?P<func>[\w\\]+(?:->|::)?\w*))?'),
    re.compile(r'(?P<path>[\w./-]+\.php) on line (?P<line>\d+)'),
    # Go:  /app/internal/pay/retry.go:42 +0x1d
    re.compile(r'(?P<path>[\w./-]+\.go):(?P<line>\d+)'),
]

# Anything else that looks like a source path, with an optional :line.
_GENERIC_PATH = re.compile(
    r'(?P<path>(?:[\w.-]+/)*[\w.-]+\.(?:py|js|jsx|ts|tsx|java|kt|go|rb|php|cs|rs|scala|swift|c|cc|cpp|h))'
    r'(?::(?P<line>\d+))?\b'
)

# Frames inside dependencies or the runtime say nothing about the diff.
_LIBRARY_MARKERS = (
    'site-packages/', 'dist-packages/', 'node_modules/', '/usr/lib/', '/usr/local/lib/',
    '<frozen', 'node:internal', '/usr/local/go/src/', '/go/pkg/mod/', '/gems/', 'vendor/',
    '/rustc/', 'java.base/',
)

_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]{4,}')
_ERROR_LINE = re.compile(r'error|exception|fail|refused|timeout|traceback|panic|fatal', re.I)
# Words too common in error lines to point at any code.
_STOPWORDS = {
    'error', 'errors', 'exception', 'traceback', 'failed', 'failure', 'warning', 'during',
    'handling', 'another', 'occurred', 'recent', 'call', 'last', 'line', 'file', 'module',
    'while', 'value', 'object', 'return', 'class', 'function', 'unknown', 'message', 'level',
    'service', 'production', 'staging', 'request', 'response', 'status', 'true', 'false', 'none',
    'null', 'undefined', 'string', 'number', 'raise', 'raised', 'thread', 'caused', 'stack',
}


def _is_library(path: str) -> bool:
    return any(marker in path for marker in _LIBRARY_MARKERS)


def extract_stack_refs(log_lines: Iterable[str], limit: int = 50) -> list[StackRef]:
    """Stack frames named in the logs, application code only, first seen first."""
    refs: list[StackRef] = []
    seen: set[tuple] = set()

    def add(path: str, line: str | None, func: str | None) -> None:
        if not path or _is_library(path):
            return
        ref = StackRef(path=path, line=int(line) if line else None, func=func or None)
        key = (ref.path, ref.line, ref.func)
        if key not in seen:
            seen.add(key)
            refs.append(ref)

    for text in log_lines or []:
        if not isinstance(text, str) or not text:
            continue
        matched_spans: list[tuple[int, int]] = []
        for pattern in _FRAME_PATTERNS:
            for m in pattern.finditer(text):
                groups = m.groupdict()
                add(groups.get('path'), groups.get('line'), groups.get('func'))
                matched_spans.append(m.span())
        for m in _GENERIC_PATH.finditer(text):
            if any(start <= m.start() < end for start, end in matched_spans):
                continue
            add(m.group('path'), m.group('line'), None)
        if len(refs) >= limit:
            break
    return refs[:limit]


def error_tokens(log_lines: Iterable[str], limit: int = 40) -> set[str]:
    """Distinctive identifiers from error lines (``ConnectionRefusedError``,
    ``query_timeout``, ``redis``): a hunk mentioning them is worth reading."""
    tokens: dict[str, int] = {}
    for text in log_lines or []:
        if not isinstance(text, str) or not _ERROR_LINE.search(text):
            continue
        for tok in _IDENTIFIER.findall(text):
            low = tok.lower()
            if low in _STOPWORDS or low.isdigit():
                continue
            tokens[low] = tokens.get(low, 0) + 1
    ranked = sorted(tokens, key=lambda t: (-tokens[t], t))
    return set(ranked[:limit])


def _file_path(f) -> str:
    if isinstance(f, dict):
        return str(f.get('path') or '')
    return str(f or '')


def _match_strength(changed_path: str, ref: StackRef) -> int:
    """How surely a frame points at a changed file: 2 = same path (or a
    path suffix), 1 = same file name only, 0 = no match."""
    if not changed_path:
        return 0
    changed = changed_path.strip('/').lower()
    ref_path = ref.path.replace('\\', '/').strip('/').lower()
    if ref_path == changed or ref_path.endswith('/' + changed) or changed.endswith('/' + ref_path):
        return 2
    if posixpath.basename(ref_path) != posixpath.basename(changed):
        return 0
    # Java frames carry only the file name; the package in the function
    # name (com.acme.pay.Retry.run) confirms the directory.
    if ref.func and '.' in ref.func:
        package_dir = '/'.join(ref.func.split('.')[:-2]).lower()
        if package_dir and package_dir in changed:
            return 2
    return 1


@dataclass
class _Hunk:
    header: str
    lines: list[str]
    new_start: int
    new_len: int
    score: int = 0
    anchor: int | None = None  # index in ``lines`` of the most relevant line

    @property
    def text(self) -> str:
        return '\n'.join([self.header, *self.lines])


_HUNK_HEADER = re.compile(r'^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<len>\d+))? @@')


def _parse_hunks(diff: str) -> list[_Hunk]:
    hunks: list[_Hunk] = []
    current: _Hunk | None = None
    preamble: list[str] = []
    for line in diff.splitlines():
        m = _HUNK_HEADER.match(line)
        if m:
            current = _Hunk(header=line, lines=[], new_start=int(m.group('start')),
                            new_len=int(m.group('len') or 1))
            hunks.append(current)
        elif current is not None:
            current.lines.append(line)
        else:
            preamble.append(line)
    if not hunks and preamble:
        # Not a unified diff (some providers send a bare patch body).
        hunks.append(_Hunk(header='', lines=preamble, new_start=1, new_len=len(preamble)))
    return hunks


def _score_hunk(hunk: _Hunk, refs: list[StackRef], tokens: set[str]) -> None:
    body_low = hunk.text.lower()
    for ref in refs:
        if ref.line is not None and hunk.new_start - LINE_SLACK <= ref.line <= hunk.new_start + hunk.new_len + LINE_SLACK:
            hunk.score += 100
            # Walk the hunk to find the line number the frame names.
            new_line = hunk.new_start
            for i, line in enumerate(hunk.lines):
                if new_line >= ref.line:
                    hunk.anchor = i
                    break
                if not line.startswith('-'):
                    new_line += 1
        func = (ref.func or '').split('.')[-1].split('->')[-1].split('::')[-1].strip('<>`\'')
        if len(func) >= 3 and func.lower() in body_low:
            hunk.score += 40
    hunk.score += 5 * sum(1 for tok in tokens if tok in body_low)


def _trim_hunk(hunk: _Hunk, budget: int) -> str:
    text = hunk.text
    if len(text) <= budget:
        return text
    lines = hunk.lines
    if hunk.anchor is not None:
        lo = max(0, hunk.anchor - LINE_WINDOW)
        hi = min(len(lines), hunk.anchor + LINE_WINDOW + 1)
    else:
        lo, hi = 0, len(lines)
    kept: list[str] = [hunk.header] if hunk.header else []
    if lo > 0:
        kept.append(f'  … {lo} lines above not shown')
    size = sum(len(k) + 1 for k in kept)
    shown = lo
    for line in lines[lo:hi]:
        if size + len(line) + 1 > budget - 40:
            break
        kept.append(line)
        size += len(line) + 1
        shown += 1
    if shown < len(lines):
        kept.append(f'  … {len(lines) - shown} more lines not shown')
    return '\n'.join(kept)


@dataclass
class _FileView:
    path: str
    diff: str
    strength: int = 0
    refs: list[StackRef] = field(default_factory=list)
    hunks: list[_Hunk] = field(default_factory=list)

    @property
    def score(self) -> int:
        best = max((h.score for h in self.hunks), default=0)
        return self.strength * 100 + best


def _excerpt(view: _FileView, budget: int) -> tuple[str, int, int]:
    """Best hunks first, in file order, inside the budget.
    Returns (text, hunks shown, hunks total)."""
    if not view.hunks:
        return '', 0, 0
    ranked = sorted(range(len(view.hunks)), key=lambda i: (-view.hunks[i].score, i))
    pieces: dict[int, str] = {}
    used = 0
    for i in ranked:
        hunk = view.hunks[i]
        if pieces and hunk.score == 0 and view.strength:
            break  # matched file: unrelated hunks are noise
        room = budget - used
        if room < 120:
            break
        pieces[i] = _trim_hunk(hunk, room)
        used += len(pieces[i]) + 1
    text = '\n'.join(pieces[i] for i in sorted(pieces))
    return text, len(pieces), len(view.hunks)


def _ref_label(refs: list[StackRef]) -> str:
    parts = []
    for ref in refs[:3]:
        bit = f'line {ref.line}' if ref.line else 'named'
        if ref.func:
            bit += f', in {ref.func}'
        parts.append(bit)
    return '; '.join(parts)


def _default_redactor():
    from Utils.data_redaction import DataRedactionService
    service = DataRedactionService()
    return lambda text: service.redact(text)[0]


def _redact_diff(text: str, redact) -> str:
    """Redact a diff excerpt line by line. ``@@`` hunk headers hold only
    line numbers and stay as they are (the phone-number pattern read
    "+88,9" as a phone number), and each diff line is redacted after its
    "+"/"-"/" " marker so the marker never becomes part of a match."""
    out = []
    for line in text.split('\n'):
        if line.startswith('@@') or line.startswith('  … '):
            out.append(line)
        elif line[:1] in ('+', '-', ' '):
            out.append(line[0] + redact(line[1:]))
        else:
            out.append(redact(line))
    return '\n'.join(out)


def build_code_changes_section(code_changes: list[dict] | None, log_lines: list[str] | None,
                               total_budget: int = TOTAL_BUDGET, redact=None) -> str:
    """The "Recent Code Changes" prompt section, with diffs chosen by the
    stack traces and error text in ``log_lines``.

    ``redact`` masks secrets and personal data in diff excerpts and commit
    messages (default: the same DataRedactionService used for logs).
    """
    if not code_changes:
        return ''
    try:
        redact = redact or _default_redactor()
    except Exception:
        redact = None

    def clean(text: str, diff: bool = False) -> str | None:
        """Redacted text, or None when redaction is unavailable: code is
        left out rather than sent unmasked."""
        if not text:
            return text
        if redact is None:
            return None
        try:
            return _redact_diff(text, redact) if diff else redact(text)
        except Exception:
            return None
    refs = extract_stack_refs(log_lines or [])
    tokens = error_tokens(log_lines or [])
    commits = code_changes[:MAX_COMMITS]

    # Rank every changed file across the window first, so the budget goes
    # to the files the logs point at, whichever commit they are in.
    views: dict[tuple[int, int], _FileView] = {}
    for ci, change in enumerate(commits):
        for fi, f in enumerate((change.get('files') or [])[:MAX_FILES_LISTED]):
            path = _file_path(f)
            diff = f.get('diff', '') if isinstance(f, dict) else ''
            view = _FileView(path=path, diff=diff or '')
            for ref in refs:
                strength = _match_strength(path, ref)
                if strength:
                    view.refs.append(ref)
                    view.strength = max(view.strength, strength)
            if view.diff:
                view.hunks = _parse_hunks(view.diff)
                for hunk in view.hunks:
                    _score_hunk(hunk, view.refs, tokens)
            views[(ci, fi)] = view

    remaining = total_budget
    excerpts: dict[tuple[int, int], tuple[str, int, int]] = {}
    order = sorted(views, key=lambda k: (-views[k].score, k))
    for key in order:
        view = views[key]
        if not view.diff or remaining < 120:
            continue
        cap = MATCHED_FILE_BUDGET if (view.strength or view.score) else UNMATCHED_FILE_BUDGET
        text, shown, total = _excerpt(view, min(cap, remaining))
        if text:
            excerpts[key] = (text, shown, total)
            remaining -= len(text)

    out = ['', 'Recent Code Changes:', '-------------', f'{len(code_changes)} commits in time window:']
    if refs:
        out.append('Diff excerpts were chosen by the stack traces and error text in the logs above; '
                   'files marked "in stack trace" are named by a frame.')
    hidden = 0
    for ci, change in enumerate(commits):
        sha = str(change.get('sha') or 'N/A')[:8]
        out.append('')
        out.append(f"[{sha}] {change.get('author', 'Unknown')} ({change.get('timestamp', 'N/A')})")
        out.append(f"  Branch: {change.get('branch', 'N/A')}")
        message = clean(str(change.get('message') or 'No message')[:100])
        out.append(f"  Message: {message if message is not None else '[withheld: redaction unavailable]'}")
        stats = change.get('stats') or {}
        if stats:
            out.append(f"  Changed: {stats.get('files', 0)} files (+{stats.get('additions', 0)}/-{stats.get('deletions', 0)})")
        files = change.get('files') or []
        if not files:
            continue
        out.append('  Files & Diffs:')
        for fi, _ in enumerate(files[:MAX_FILES_LISTED]):
            view = views[(ci, fi)]
            label = f'    File: {view.path or "unknown"}'
            if view.refs:
                label += f'  [in stack trace: {_ref_label(view.refs)}]'
            out.append(label)
            if (ci, fi) in excerpts:
                text, shown, total = excerpts[(ci, fi)]
                text = clean(text, diff=True)
                if text is None:
                    out.append('    Diff: withheld (redaction unavailable)')
                    continue
                note = f' ({shown} of {total} hunks)' if total > shown else ''
                out.append(f'    Diff{note}:')
                out.append(text)
            elif view.diff:
                hidden += 1
        if len(files) > MAX_FILES_LISTED:
            out.append(f'    ... and {len(files) - MAX_FILES_LISTED} more files')
    if hidden:
        out.append(f'\n(Diffs of {hidden} other files left out to stay within the prompt budget.)')
    if len(code_changes) > MAX_COMMITS:
        out.append(f'\n... and {len(code_changes) - MAX_COMMITS} older commits not shown')
    return '\n'.join(out) + '\n'
