"""Redaction helpers for non-log data types (Q1.5).

Traces + alert payloads flow to third-party AI providers via the
RCA prompt. The existing ``DataRedactionService`` was written for
log messages; these helpers apply the same policy to structured
data shapes (trace summaries, alert-event fields) with a single
service instance per call for efficiency.

Design:

* **Fail-open, never raise.** If redaction breaks, callers keep the
  unredacted value — a broken redactor must NOT stop the batch
  pipeline. The same trade-off ``ai_model.tasks._redact_log_messages``
  already accepts.
* **Idempotent.** Redacting already-redacted text yields the same
  output — safe to call at multiple layers (defence in depth).
* Small helpers only — no queryset walking. Callers pass in dicts /
  strings; we return the same shape.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _service():
    """Return a DataRedactionService instance, or None if the import fails."""
    try:
        from Utils.data_redaction import DataRedactionService
        return DataRedactionService()
    except Exception as exc:
        logger.warning('DataRedactionService unavailable: %s', exc)
        return None


def redact_text(text: Optional[str]) -> str:
    """Redact one string. Empty / None → empty string. Never raises."""
    if not text:
        return ''
    svc = _service()
    if svc is None:
        return text
    try:
        redacted, _findings = svc.redact(text)
        return redacted
    except Exception as exc:
        logger.warning('redact_text failed (returning original): %s', exc)
        return text


def redact_span_summary(summary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Redact the trace summary shape produced by ``ai_model.trace_context``.

    Fields redacted:

    * ``top_slow[*].operation_name``   — often includes path params (user IDs)
    * ``top_errors[*].operation_name`` — same
    * ``top_errors[*].status_message`` — free-text error text often includes PII
    * ``services_touched`` — service names are usually safe but we redact
      defensively in case someone parametrised badly

    Returns a NEW dict — callers can safely persist without mutating the
    input.
    """
    if not isinstance(summary, dict):
        return summary
    svc = _service()
    if svc is None:
        return summary

    def _r(v):
        if not v or not isinstance(v, str):
            return v
        try:
            out, _ = svc.redact(v)
            return out
        except Exception:
            return v

    out = dict(summary)
    for key in ('top_slow', 'top_errors'):
        rows = summary.get(key) or []
        if not isinstance(rows, list):
            continue
        out[key] = [
            {**row,
             'operation_name': _r(row.get('operation_name')),
             'status_message': _r(row.get('status_message')),
             'service_name': _r(row.get('service_name')),
             }
            for row in rows
            if isinstance(row, dict)
        ]
    if isinstance(summary.get('services_touched'), list):
        out['services_touched'] = [_r(s) for s in summary['services_touched']]
    return out


def redact_alert_parsed(parsed: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Redact the parsed-alert shape produced by ``Data.alert_webhooks``
    (before persisting to ``AlertEvent`` + before enqueuing analysis).

    Fields redacted:

    * ``summary``   — free-text alert description; frequently
                      includes IDs / IPs / hostnames from user tags.
    * ``alertname`` — usually short + safe but redact defensively.
    * ``service`` + ``environment`` — labels; short + typically safe
      but same defensive posture.

    ``external_id``, ``state``, and ``severity`` are enum-shaped and
    left as-is (redacting them would corrupt dedup + severity floor
    comparisons).
    """
    if not isinstance(parsed, dict):
        return parsed
    svc = _service()
    if svc is None:
        return parsed

    def _r(v):
        if not v or not isinstance(v, str):
            return v
        try:
            out, _ = svc.redact(v)
            return out
        except Exception:
            return v

    out = dict(parsed)
    for key in ('summary', 'alertname', 'service', 'environment'):
        if key in out:
            out[key] = _r(out[key])
    return out


def redact_raw_payload(payload: Optional[Dict[str, Any]], max_depth: int = 8) -> Dict[str, Any]:
    """
    Best-effort redact of arbitrary JSON stored on
    ``AlertEvent.raw_payload``.

    Walks the dict recursively, redacting string leaves. Skips
    non-string keys / values (numbers, booleans, nulls). Depth-capped
    to avoid pathological input.

    **Depth calibration**: real Alertmanager payloads have leaves at
    depth 4 (``{alerts: [{annotations: {summary: ...}}]}``); Datadog
    payloads are shallower. Cap at 8 which covers both with headroom
    while still bounding any pathological adversarial input. Tests
    verify the cap holds.

    Returns a new dict; input is unchanged.
    """
    svc = _service()
    if svc is None or not isinstance(payload, dict):
        return payload if isinstance(payload, dict) else {}

    def _walk(node: Any, depth: int) -> Any:
        if depth <= 0:
            return node
        if isinstance(node, str):
            try:
                out, _ = svc.redact(node)
                return out
            except Exception:
                return node
        if isinstance(node, list):
            return [_walk(v, depth - 1) for v in node]
        if isinstance(node, dict):
            return {k: _walk(v, depth - 1) for k, v in node.items()}
        # int / float / bool / None — pass through
        return node

    return _walk(payload, max_depth)
