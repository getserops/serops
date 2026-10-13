"""B1 · Metrics look healthy (scrape gap hid the spike), logs are flooding errors."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'B1'
TIER = 2


def run(ctx):
    logs = [mk_log('ERROR', f'redis.pool: connection refused (attempt {i+1})', 300 - i*8) for i in range(30)]
    logs += [mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 30)]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        # Metrics show a "healthy" p95 — but the scrape had a gap
        metrics_summary={
            'error_rate_pct': 1.2,
            'p95_latency_ms': 90,
            'scrape_gap_seconds': 240,
        },
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
    # AI must not declare 'no incident' based on healthy metrics
    root_cause_does_not_contain=['no incident', 'appears healthy', 'all is well'],
)
