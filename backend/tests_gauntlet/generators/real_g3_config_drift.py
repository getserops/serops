"""G3 · Config drift — same code, dev/staging fine, prod broken (env-var-only diff)."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'G3'
TIER = 3


def run(ctx):
    logs = [
        mk_log('INFO',  'app.startup: v1.4.7 · env=production · REDIS_URL=redis-cache-2.internal:6380', 300),
        mk_log('ERROR', 'redis.pool: connection refused (redis-cache-2.internal:6380)', 240),
        mk_log('ERROR', 'ops.diff: prod REDIS_URL differs from staging (staging=redis-cache-1.internal:6379)', 180),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 88.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['config', 'env', 'redis_url', 'prod', 'drift', 'redis'],
)
