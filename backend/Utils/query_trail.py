"""Opt-in record of what SerOps asked each store and what the store answered.

Off by default, for debugging and benchmarks. The answers are written raw,
not redacted (see below). Off unless ``SEROPS_QUERY_TRAIL_DIR`` names a directory. Then every request
an investigation (``investigation-<id>.jsonl``) or a batch analysis
(``<batch_id>.jsonl``) sends to a log, metric, trace or code store is
appended to that file as one JSON line: the method, the URL (credentials
removed), the request body, the status and the answer. It is written where
all store traffic leaves the backend: ``Utils.outbound`` for the adapters
built on requests, the Elasticsearch / OpenSearch connection classes, and
the Google Cloud Monitoring client.

What it is for: benchmark runs on test estates, where "did SerOps read the
evidence" has to be answered from saved data. It is not an audit log and it
is not meant for production: the answers are stored as the stores returned
them, before redaction, so the directory must stay on the pod (the chart
uses the pod's /tmp emptyDir) and whoever collects it redacts it.
Request headers are never recorded, so tokens sent as headers never reach it.

Recording must never change what the product does: every failure here is
logged and swallowed, and nothing is read from a response that the caller
would not read anyway.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

logger = logging.getLogger(__name__)

ENV_VAR = 'SEROPS_QUERY_TRAIL_DIR'
# Per request and per answer. A Loki answer for a busy window is a few MB;
# anything past this is cut and marked, never silently dropped.
MAX_BODY_CHARS = 5_000_000

_current = contextvars.ContextVar('serops_query_trail', default=None)
_lock = threading.Lock()
_SAFE_KEY = re.compile(r'[^A-Za-z0-9_.-]')
_SENSITIVE_PARAM = re.compile(r'(key|token|secret|passw|auth|signature|sig$|credential|session)', re.I)


def trail_dir() -> str:
    return (os.environ.get(ENV_VAR) or '').strip()


@contextmanager
def recording(key):
    """Record store traffic into ``<dir>/<key>.jsonl`` for the duration.

    A no-op (yields None) when the trail is off or ``key`` is empty.
    """
    directory = trail_dir()
    if not directory or not key:
        yield None
        return
    path = os.path.join(directory, _SAFE_KEY.sub('_', str(key)) + '.jsonl')
    token = _current.set(path)
    try:
        yield path
    finally:
        _current.reset(token)


def active() -> bool:
    return _current.get() is not None


def safe_url(url) -> str:
    """The URL without user:password and with credential-like query values masked."""
    try:
        parts = urlsplit(str(url))
        netloc = parts.netloc.rsplit('@', 1)[-1]
        query = urlencode([(k, '[REDACTED]' if _SENSITIVE_PARAM.search(k) else v)
                           for k, v in parse_qsl(parts.query, keep_blank_values=True)])
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
    except Exception:                                   # noqa: BLE001
        return '[unparseable url]'


def _as_text(value):
    """``(text, truncated)`` for a body of any shape."""
    if value is None:
        return '', False
    if isinstance(value, (bytes, bytearray, memoryview)):
        text = bytes(value).decode('utf-8', errors='replace')
    elif isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, default=str)
        except Exception:                               # noqa: BLE001
            text = repr(value)
    if len(text) > MAX_BODY_CHARS:
        return text[:MAX_BODY_CHARS], True
    return text, False


def record(store, method, url, request_body=None, status=None, response_body=None,
           error=None, started=None):
    """Append one exchange to the active trail. Never raises."""
    path = _current.get()
    if path is None:
        return
    try:
        request_text, request_cut = _as_text(request_body)
        response_text, response_cut = _as_text(response_body)
        line = {
            'at': datetime.now(timezone.utc).isoformat(),
            'store': str(store or ''),
            'method': str(method or ''),
            'url': safe_url(url),
            'request': request_text,
            'status': status,
            'response': response_text,
            'truncated': request_cut or response_cut,
            'error': str(error) if error else None,
            'ms': round((time.monotonic() - started) * 1000) if started else None,
        }
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        data = (json.dumps(line, default=str) + '\n').encode('utf-8')
        with _lock:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
    except Exception as exc:                            # noqa: BLE001
        logger.warning('query trail: could not record a %s request: %s', method, exc)


def host_of(url) -> str:
    try:
        return urlsplit(str(url)).netloc.rsplit('@', 1)[-1]
    except Exception:                                   # noqa: BLE001
        return ''
