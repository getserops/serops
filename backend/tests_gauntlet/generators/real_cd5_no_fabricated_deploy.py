"""CD5 · No fabricated deploy correlation.

The original plan named this ``skipped-conditional-stage`` (pipeline
'success' but deploy stage skipped via ``only:tags``). The same class
of bug is testable more directly: a batch with a real infrastructure
outage and ZERO code_changes / ZERO deployments in-window. The AI
must NOT fabricate "a recent deploy caused this" — a common hallucination
when the prompt over-emphasises deploy correlation.

Also asserts the root_cause does not contain fake commit SHAs like
'deadbeef', 'abc123', 'a1b2c3d4', etc — the AI sometimes invents these
when it thinks a deploy is involved.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'CD5'
TIER = 0


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(level: str, msg: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def run(ctx):
    from tests_gauntlet._core import create_batch

    # Real infra outage. NO code_changes. NO deployments. NO commits.
    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=[
            _log('ERROR', 'redis.pool: connection refused to redis:6379', 6),
            _log('ERROR', 'redis.pool: 47 consecutive refusals — circuit breaker OPEN', 5),
            _log('ERROR', 'checkout.cache: falling back to DB reads — p95 +340ms', 4),
            _log('ERROR', 'checkout.cache: DB read pool exhausted — 500 responses', 3),
            _log('ERROR', 'checkout: rejecting new sessions', 2),
            _log('ERROR', 'checkout: 100% error rate on /checkout POSTs', 1),
        ],
        metrics_summary={'error_rate_pct': 100.0, 'p95_latency_ms': 5200},
        code_changes=[],  # explicit — no deployment chain
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains=['redis'],
    # No fabricated deploy blame: none of the common "invented commit"
    # phrases should appear in the analysis narrative.
    root_cause_does_not_contain=[
        'recent deploy', 'recent commit', 'commit caused', 'deploy caused',
        'deadbeef', 'a1b2c3', 'abc123',
    ],
    timed_out_ok=False,
)
