"""C3 · Service flaps healthy/unhealthy every ~40s for 30 min. Must collapse to ≤3 issues."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'C3'
TIER = 2


def run(ctx):
    logs = []
    for i in range(45):  # 45 flap cycles over ~30 min
        t = 1800 - i * 40
        logs.append(mk_log('ERROR', 'checkout: healthcheck FAIL · pod restarting', t))
        logs.append(mk_log('INFO',  'checkout: healthcheck OK · pod ready', t - 20))
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 22.0, 'restart_count': 45},
    )


EXPECTATION = Expectation(
    min_issues=1,
    # Should be ONE flapping issue, not 45. Allow 1-3 for AI phrasing variance.
    max_issues=3,
    root_cause_contains_any=['flap', 'restart', 'healthcheck', 'health check', 'oscillat'],
)
