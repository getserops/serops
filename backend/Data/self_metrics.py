"""SerOps self-metrics — Prometheus exposition endpoint (Item #24).

Exposes operational metrics about SerOps itself (not the tenant data
it analyses) so on-call SREs can scrape it with their own Prometheus.
Standard SRE table-stakes.

Endpoint:

    GET /metrics/
    Optional: Authorization: Basic <base64> if SEROPS_METRICS_BASIC_AUTH set

Response: Prometheus text exposition format (Content-Type:
text/plain; version=0.0.4).

Metrics exposed (all counters unless noted):

    serops_batch_created_total{outcome=[created|skipped]}
    serops_batch_analyzed_total{provider=[claude|openai|deepseek|...],
                                outcome=[success|error|timeout]}
    serops_ai_tokens_total{provider, direction=[input|output]}
    serops_alert_received_total{source=[alertmanager|grafana|datadog],
                                outcome=[accepted|deduplicated|rejected]}
    serops_otlp_spans_received_total   (counter)
    serops_http_requests_total{method, endpoint_group, status_class}
                              (via middleware — cheap group labels only)
    serops_up                 (gauge, always 1 — health probe target)

Design:

* Uses a **process-local registry** — safe for multi-worker gunicorn
  because each worker exposes its own set (Prometheus multi-process
  mode is out of scope for MVP; scrape each pod separately in K8s).
* No cardinality bombs: request labels are grouped (e.g., all
  ``/api/data/batches/<id>/`` collapse to ``data_batch_detail``) so
  we never explode past ~50 series.
* Auth is optional. Default: open (K8s scrape from private network).
  Toggle basic-auth with ``SEROPS_METRICS_BASIC_AUTH=user:pass`` env.
"""

from __future__ import annotations

import base64
import hmac
import logging
import os
import re

from django.http import HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest,
)
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry + metric definitions
# ---------------------------------------------------------------------------
#
# We use a dedicated CollectorRegistry so tests can reset state without
# touching the default registry (which also holds process/gc metrics
# from prometheus_client).

REGISTRY = CollectorRegistry(auto_describe=True)


BATCH_CREATED = Counter(
    'serops_batch_created_total',
    'Batches created by the pipeline. `outcome` is created or skipped.',
    ['outcome'],
    registry=REGISTRY,
)

BATCH_ANALYZED = Counter(
    'serops_batch_analyzed_total',
    'Batches fed to an AI provider. `provider` is normalized, '
    '`outcome` is success/error/timeout/skipped.',
    ['provider', 'outcome'],
    registry=REGISTRY,
)

AI_TOKENS = Counter(
    'serops_ai_tokens_total',
    'Tokens consumed by AI provider calls. `direction` is input or output.',
    ['provider', 'direction'],
    registry=REGISTRY,
)

ALERT_RECEIVED = Counter(
    'serops_alert_received_total',
    'Alert webhooks accepted. `source` = alertmanager/grafana/datadog. '
    '`outcome` = accepted/deduplicated/rejected.',
    ['source', 'outcome'],
    registry=REGISTRY,
)

OTLP_SPANS_RECEIVED = Counter(
    'serops_otlp_spans_received_total',
    'Spans successfully persisted via the OTLP receiver.',
    registry=REGISTRY,
)

HTTP_REQUESTS = Counter(
    'serops_http_requests_total',
    'HTTP requests handled by the API. `endpoint_group` is bucketed to '
    'avoid cardinality explosion (e.g. /api/data/batches/<id>/ → '
    'data_batch_detail).',
    ['method', 'endpoint_group', 'status_class'],
    registry=REGISTRY,
)

UP = Gauge(
    'serops_up',
    'Always 1 while the process is serving traffic. Scrape target liveness.',
    registry=REGISTRY,
)
UP.set(1)


# ---------------------------------------------------------------------------
# Endpoint bucketing — the middleware calls this
# ---------------------------------------------------------------------------

_ROUTE_BUCKETS = [
    # Order matters: first match wins. Keep specific rules before generic.
    (re.compile(r'^/api/data/batches/[^/]+/history/?$'), 'data_batch_history'),
    (re.compile(r'^/api/data/batches/[^/]+/timeline/?$'), 'data_batch_timeline'),
    (re.compile(r'^/api/data/batches/[^/]+/correlations/?$'), 'data_batch_correlations'),
    (re.compile(r'^/api/data/batches/[^/]+/?$'), 'data_batch_detail'),
    (re.compile(r'^/api/data/batches/?$'), 'data_batch_list'),
    (re.compile(r'^/api/data/issues/[^/]+/?$'), 'data_issue_action'),
    (re.compile(r'^/api/data/issues/?$'), 'data_issue_list'),
    (re.compile(r'^/api/data/analytics/'), 'data_analytics'),
    (re.compile(r'^/api/data/settings/'), 'data_settings'),
    (re.compile(r'^/api/traces/v1/traces/?$'), 'otlp_traces'),
    (re.compile(r'^/api/traces/traces/'), 'traces_read'),
    (re.compile(r'^/api/traces/keys/'), 'traces_keys'),
    (re.compile(r'^/api/webhooks/alerts/'), 'alert_webhook'),
    (re.compile(r'^/api/webhooks/'), 'other_webhook'),
    (re.compile(r'^/api/integrations/'), 'integrations'),
    (re.compile(r'^/api/organisation/'), 'organisation'),
    (re.compile(r'^/api/projects/'), 'projects'),
    (re.compile(r'^/api/services/'), 'services'),
    (re.compile(r'^/api/settings/'), 'settings'),
    (re.compile(r'^/api/auth/'), 'auth'),
    (re.compile(r'^/api/chat/'), 'chat'),
    (re.compile(r'^/api/notification/'), 'notification'),
    (re.compile(r'^/api/providers/'), 'providers'),
    (re.compile(r'^/api/health/?$'), 'health'),
    (re.compile(r'^/metrics/?$'), 'metrics'),
]


def bucket_endpoint(path: str) -> str:
    """Map a URL path to a low-cardinality bucket label."""
    if not path:
        return 'other'
    for pat, label in _ROUTE_BUCKETS:
        if pat.match(path):
            return label
    return 'other'


def bucket_status(status_code) -> str:
    """Group HTTP status codes into 2xx/3xx/4xx/5xx for low cardinality."""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return 'other'
    if 200 <= code < 300:
        return '2xx'
    if 300 <= code < 400:
        return '3xx'
    if 400 <= code < 500:
        return '4xx'
    if 500 <= code < 600:
        return '5xx'
    return 'other'


# ---------------------------------------------------------------------------
# Middleware — request counter
# ---------------------------------------------------------------------------


class PrometheusRequestMiddleware:
    """Counts HTTP requests by method + endpoint bucket + status class.

    Placed after the response is generated — the counter is O(1) per
    request; no impact on latency-critical hot paths.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            HTTP_REQUESTS.labels(
                method=request.method,
                endpoint_group=bucket_endpoint(request.path or ''),
                status_class=bucket_status(response.status_code),
            ).inc()
        except Exception:
            # Metrics collection must NEVER fail a request.
            pass
        return response


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


class MetricsView(APIView):
    """Prometheus text-format exposition."""

    # We accept AllowAny + verify basic-auth ourselves when configured.
    # This keeps the endpoint scrapable from an unauthenticated Prom
    # in the private network case (the default).
    permission_classes = [AllowAny]

    def get(self, request):
        expected = os.getenv('SEROPS_METRICS_BASIC_AUTH', '').strip()
        if expected:
            if not self._check_basic_auth(request, expected):
                return HttpResponse(
                    'Unauthorized',
                    status=401,
                    headers={'WWW-Authenticate': 'Basic realm="serops-metrics"'},
                )
        payload = generate_latest(REGISTRY)
        return HttpResponse(payload, content_type=CONTENT_TYPE_LATEST)

    @staticmethod
    def _check_basic_auth(request, expected: str) -> bool:
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.startswith('Basic '):
            return False
        try:
            decoded = base64.b64decode(header[len('Basic '):]).decode('utf-8')
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(decoded, expected)
