"""I1 · Runbook loop — alert triggers a runbook which triggers a new alert. Detect the loop."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'I1'
TIER = 3


def run(ctx):
    logs = [
        mk_log('WARN',  'alertmanager: HighErrorRate FIRING · runbook triggered', 320),
        mk_log('INFO',  'runbook.restart-checkout: dispatching kill-9 to checkout pods', 300),
        mk_log('WARN',  'kube: 3 checkout pods restarted', 280),
        mk_log('ERROR', 'alertmanager: HighErrorRate FIRING (again) · runbook triggered', 220),
        mk_log('INFO',  'runbook.restart-checkout: dispatching kill-9 (iteration 2)', 200),
        mk_log('ERROR', 'alertmanager: HighErrorRate FIRING (iteration 3) · runbook triggered', 120),
        mk_log('ERROR', 'ops: detected runbook loop · disabling automation', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 61.0, 'restart_count': 9},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['runbook', 'loop', 'restart', 'automation'],
)
