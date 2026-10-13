"""CD2 · Bug shipped 2 days ago, revert PR merged now. Don't blame the revert."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CD2'
TIER = 4


def run(ctx):
    now = datetime.now(timezone.utc)
    logs = [
        mk_log('ERROR', 'checkout.tax: division by zero on VAT rounding', 400),
        mk_log('INFO',  'kube.deploy: rolling back to 1.4.9 · commit revert001', 200),
        mk_log('INFO',  'error rate 0.4% · normal', 60),
    ]
    code_changes = [
        {
            'sha': 'b4d0000c', 'commit_sha': 'b4d0000c', 'author': 'dev-alice',
            'message': 'refactor(checkout): simplify tax rounding logic',
            'timestamp': (now - timedelta(hours=48)).isoformat(),
            'files_changed': ['services/checkout/tax.py'],
        },
        {
            'sha': 'revert001', 'commit_sha': 'revert001', 'author': 'ops-bot',
            'message': 'Revert "refactor(checkout): simplify tax rounding logic"',
            'timestamp': (now - timedelta(seconds=220)).isoformat(),
            'files_changed': ['services/checkout/tax.py'],
        },
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 12.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['b4d0000c', 'tax', 'division', 'rounding', 'VAT', 'vat'],
    # Anti-goal: blaming the revert
    root_cause_does_not_contain=['revert001', 'the revert', 'rollback caused'],
)
