"""PA1 · Canonical log-field names — same incident logged 3 ways, ingest still coherent.

Simplified from the original "3 log adapters" plan: instead of wiring 3
providers, we submit the same incident with fields shaped as Loki/Datadog/
Elasticsearch would produce them. All 3 shapes must survive the canonical
field mapping and produce ONE coherent analysis (not 3 fragmented ones).
"""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'PA1'
TIER = 2


def run(ctx):
    # Loki-like: labels flattened, message under 'msg'
    loki = mk_log('ERROR', 'redis.pool: connection refused to redis:6379', 240)
    # Datadog-like: service + status keys
    dd = mk_log('ERROR', 'redis.pool: pool exhausted after 40 refusals', 180)
    dd['status'] = 'error'
    # ES-like: full canonical
    es = mk_log('ERROR', 'checkout: rejecting new sessions — Redis unreachable', 60)
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=[loki, dd, es],
        metrics_summary={'error_rate_pct': 78.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection', 'pool'],
)
