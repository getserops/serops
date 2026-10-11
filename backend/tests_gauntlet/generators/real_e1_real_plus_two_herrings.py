"""E1 · Real incident plus two unrelated red-herring signals.

The batch contains three noisy signal groups in the same time window:

1. REAL — Redis outage on the checkout service (the actual root cause)
2. HERRING — Trivy CVE scanner emitting ERROR-level "vulnerability found"
   findings against unrelated container images. Level=ERROR, but not
   a production incident — a scheduled scan.
3. HERRING — cron job overrun: nightly report generation ran 47 minutes
   over its window. Serious sounding, actually harmless.

The AI must pick the Redis outage as the primary root cause. If it
gets sidetracked and blames the CVE scanner or the cron overrun,
that's a signal-discrimination failure.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'E1'
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
        # === REAL incident: Redis outage on checkout ===
        _log('checkout', 'ERROR',
             'redis.pool: connection refused to redis:6379 · attempt 1', 300),
        _log('checkout', 'ERROR',
             'redis.pool: connection refused to redis:6379 · attempt 12', 240),
        _log('checkout', 'ERROR',
             'checkout.cache: circuit breaker OPEN after 47 refusals', 180),
        _log('checkout', 'ERROR',
             'checkout: rejecting new sessions — cache dependency down', 120),
        _log('checkout', 'ERROR',
             'checkout: 500 on POST /checkout/confirm (session store unreachable)', 60),

        # === HERRING #1: Trivy CVE scanner spam ===
        _log('trivy-scanner', 'ERROR',
             'CVE-2024-2961 CRITICAL: glibc buffer overflow in image acme/api:1.4.2', 290),
        _log('trivy-scanner', 'ERROR',
             'CVE-2024-3094 HIGH: liblzma backdoor in image acme/worker:2.1', 280),
        _log('trivy-scanner', 'ERROR',
             'CVE-2023-38408 MEDIUM: openssh in image acme/redis-mirror:6.2', 270),
        _log('trivy-scanner', 'INFO',
             'scan complete: 3 CRITICAL, 12 HIGH, 47 MEDIUM findings', 260),

        # === HERRING #2: cron overrun ===
        _log('reports-cron', 'ERROR',
             'nightly-revenue-report: exceeded 30m window · elapsed 77m', 200),
        _log('reports-cron', 'ERROR',
             'nightly-revenue-report: killed by watchdog', 160),
    ]

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={'error_rate_pct': 62.0, 'p95_latency_ms': 4100},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains=['redis'],
    # Don't blame the scanner or the cron job.
    root_cause_does_not_contain=[
        'cve', 'trivy', 'buffer overflow',
        'nightly-revenue', 'watchdog', 'cron overrun',
    ],
    timed_out_ok=False,
)
