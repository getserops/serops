"""E2 · Bad canary — 5% traffic broken, aggregate healthy, p99 tells the story."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'E2'
TIER = 3


def run(ctx):
    logs = [
        mk_log('INFO',  'canary rollout: 5% traffic to checkout:v2 (commit ca7ary5)', 300),
        mk_log('WARN',  'canary error rate 26% vs stable 0.4% (spread p99=6100ms)', 240),
        mk_log('ERROR', 'checkout:v2 · Deserialize error on new cart schema', 200),
        mk_log('ERROR', 'checkout:v2 · 500 on POST /checkout/confirm (5% of users)', 120),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        # Aggregate looks healthy but p99 is bad
        metrics_summary={
            'error_rate_pct': 1.3,           # 5% × 26% ≈ 1.3
            'p50_latency_ms': 340,
            'p99_latency_ms': 5900,
        },
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['canary', 'v2', 'ca7ary5', 'deserial', 'schema', 'deploy'],
)
