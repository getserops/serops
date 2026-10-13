"""F1 · Bad deploy → OOM → traffic reroute → replica overload → alert.

Five-link causal chain that the AI needs to trace:

    commit c0ffee12 (bad deploy)
        ↓
    memory leak in checkout pods
        ↓
    OOMKilled → pod restart storm
        ↓
    Kubernetes reroutes traffic to remaining replicas
        ↓
    remaining replicas overloaded → 5xx cascade → alerts fire

The signals span logs, metrics, and code_changes. The AI must name
the deploy (commit c0ffee12 OR the caching change) as the actual
root, not blame "OOMKill" or "traffic overload" — which are the
symptoms 2 and 3 hops out.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'F1'
TIER = 1


def _t(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _log(service: str, level: str, msg: str, seconds_ago: int) -> dict:
    return {
        'timestamp': _t(seconds_ago),
        '@timestamp': _t(seconds_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': service,
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def run(ctx):
    from tests_gauntlet._core import create_batch

    logs = [
        # Just after the deploy (t=580s): first symptom = memory rising
        _log('checkout', 'INFO', 'app.startup: 1.4.2 ready · commit c0ffee12', 580),
        _log('checkout', 'WARNING',
             'heap.usage: 78% · trend +8pp/min · leak candidate', 480),
        _log('checkout', 'WARNING',
             'heap.usage: 92% · full-gc pauses 2400ms', 380),

        # OOMKill event
        _log('checkout', 'ERROR',
             'OOMKilled: pid 2847 exceeded 512Mi limit · restarting pod', 320),
        _log('checkout', 'ERROR',
             'OOMKilled: pid 2851 exceeded 512Mi limit · restarting pod', 280),
        _log('checkout', 'ERROR',
             'OOMKilled: pid 2856 exceeded 512Mi limit · restarting pod', 240),

        # Traffic reroute + remaining replicas overloaded
        _log('kube-scheduler', 'INFO',
             'traffic reroute: 3 healthy checkout pods → 1 healthy', 220),
        _log('checkout', 'ERROR',
             'p95 latency 8400ms · queue depth 512 · overloaded', 180),
        _log('checkout', 'ERROR',
             'connection pool exhausted · 90% requests timing out', 120),

        # Alerts fire
        _log('alertmanager', 'ERROR',
             'FIRING checkout-p95-latency > 5000ms (current 8400ms)', 90),
        _log('alertmanager', 'ERROR',
             'FIRING checkout-error-rate > 20% (current 78%)', 60),
    ]

    code_changes = [
        {
            'sha': 'c0ffee12',
            'commit_sha': 'c0ffee12',
            'author': 'dev-alice',
            'message': (
                'feat(checkout): switch cache to unbounded in-memory LRU\n\n'
                'Removes the max-entries cap on the internal request cache. '
                'Trading memory for speed.'
            ),
            'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=620)).isoformat(),
            'files_changed': ['services/checkout/cache.py'],
        },
    ]

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={
            'memory': {'usage_percent': {'avg': 87.0, 'p95': 96.0}},
            'error_rate_pct': 78.0,
            'p95_latency_ms': 8400,
        },
        code_changes=code_changes,
    )


EXPECTATION = Expectation(
    min_issues=1,
    # Success: AI reaches back to the memory root cause — commit,
    # cache change, memory leak, memory pressure, or OOM. Anything
    # upstream of "traffic overload" or "connection pool exhausted".
    root_cause_contains_any=[
        'c0ffee12', 'deploy', 'cache', 'memory leak',
        'unbounded', 'lru', 'commit', 'memory', 'oom', 'heap',
    ],
    timed_out_ok=False,
)
