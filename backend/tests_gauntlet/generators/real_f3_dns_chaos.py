"""F3 · DNS chaos — 1% resolution failures for 20 min → circuit break → full outage."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'F3'
TIER = 3


def run(ctx):
    logs = [
        mk_log('WARN',  'dns.resolve: no answer for redis.internal (attempt 1)', 420),
        mk_log('WARN',  'dns.resolve: no answer for redis.internal (attempt 2)', 360),
        mk_log('ERROR', 'dns.resolve: 47 failures in 5 min (1.2% rate)', 300),
        mk_log('ERROR', 'checkout: circuit breaker OPEN for redis (partial evidence)', 240),
        mk_log('ERROR', 'checkout: cascading 500s from Redis dependency', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 78.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['dns', 'resolv', 'network', 'redis'],
)
