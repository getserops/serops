"""C1 · 5-hop cascade.

A real production outage where root and symptom are 5 services apart:

    postgres-primary (root)  →  redis-cache  →  api-gateway
                                                    ↓
                                              checkout-service
                                                    ↓
                                              frontend (alerts fire HERE)

The frontend alert fires ~8 minutes after the root cause. The AI's
job is to walk the chain back to postgres-primary, not blame the
frontend.

Signals available:
* Logs from all 5 services (interleaved by timestamp)
* Metrics: p95 latency spike on each service, starting from postgres
  and propagating up.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'C1'
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

    # Timeline (seconds ago, oldest first)
    # T-480 : postgres-primary — slow query alarm, root cause is here
    # T-420 : redis-cache — cache miss rate spikes (writes stalled)
    # T-360 : api-gateway — upstream latency spike, retries start
    # T-240 : checkout-service — request timeouts, 500s appearing
    # T-120 : frontend — page-load errors, alerts fire
    logs = [
        # Postgres — root
        _log('postgres-primary', 'ERROR',
             'autovacuum blocked on relation "orders" — dead tuples '
             '4.2M, index bloat 78%', 480),
        _log('postgres-primary', 'ERROR',
             'slow query WARNING: SELECT * FROM orders WHERE '
             'user_id = $1 · duration=8420ms', 465),
        _log('postgres-primary', 'ERROR',
             'connection pool at 240/250, holding transactions '
             'for autovacuum', 450),

        # Redis — 1st victim
        _log('redis-cache', 'WARNING',
             'cache.write: 340ms · slower than 10ms baseline · '
             'blocked on postgres session store', 420),
        _log('redis-cache', 'ERROR',
             'session-store: eviction rate up 40x — cache thrashing', 400),

        # API gateway — 2nd hop
        _log('api-gateway', 'WARNING',
             'upstream latency p95=1200ms (baseline 60ms) '
             'target=session-store', 360),
        _log('api-gateway', 'ERROR',
             'circuit breaker HALF_OPEN for /sessions/*', 320),

        # Checkout — 3rd hop
        _log('checkout', 'ERROR',
             '502 upstream timeout at /sessions/create — abandoning '
             'cart flow', 240),
        _log('checkout', 'ERROR',
             '500 InternalServerError · cascade from api-gateway '
             'circuit break', 210),

        # Frontend — 4th hop (where alerts fire)
        _log('frontend', 'ERROR',
             'checkout button unresponsive · 500 from /api/checkout', 120),
        _log('frontend', 'ERROR',
             'page-load error: cart hydrate failed', 90),
        _log('frontend', 'ERROR',
             'user-reported abandon: 3× retry, all failed', 60),
    ]

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={
            'p95_latency_ms': 5200,
            'error_rate_pct': 47.0,
            'affected_services': ['postgres-primary', 'redis-cache',
                                   'api-gateway', 'checkout', 'frontend'],
        },
    )


EXPECTATION = Expectation(
    min_issues=1,
    # The AI must trace back to the actual root. Any of these
    # keywords means the AI got somewhere upstream of the frontend
    # symptom.
    root_cause_contains_any=['postgres', 'database', 'autovacuum', 'orders'],
    # Explicit anti-goals: don't blame the last-hop symptom.
    root_cause_does_not_contain=['checkout button', 'page-load error'],
    timed_out_ok=False,
)
