"""F2 · Feature flag flip → new code path deadlocks DB pool → 500s."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'F2'
TIER = 2


def run(ctx):
    logs = [
        mk_log('INFO',  'launchdarkly: flag "checkout.parallel_writes" flipped ON at 14:00Z', 360),
        mk_log('WARN',  'db.pool: acquire slow · avg 240ms (baseline 8ms)', 320),
        mk_log('ERROR', 'db.pool: deadlock detected · victim=session_write', 280),
        mk_log('ERROR', 'db.pool: 47 waiters queued · pool exhausted', 220),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm (pool timeout 30s)', 90),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 61.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=[
        'flag', 'launchdarkly', 'parallel_writes', 'deadlock', 'pool', 'db',
    ],
)
