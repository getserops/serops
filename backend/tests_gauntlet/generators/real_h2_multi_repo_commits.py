"""H2 · Bug spans changes in service-a repo + shared-lib repo, deployed via different pipelines."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'H2'
TIER = 3


def run(ctx):
    now = datetime.now(timezone.utc)
    logs = [
        mk_log('INFO',  'app.startup: checkout v2.0 · commit ch3ckout1 · shared-lib v1.4 (commit sh4red1ib)', 300),
        mk_log('ERROR', 'checkout.tax: shared-lib.tax.round() signature mismatch — TypeError', 240),
        mk_log('ERROR', 'checkout.tax: 100% failure on VAT lines', 60),
    ]
    code_changes = [
        {
            'sha': 'ch3ckout1', 'commit_sha': 'ch3ckout1', 'author': 'dev-checkout',
            'message': 'chore(checkout): bump shared-lib to v1.4 (breaking API)',
            'timestamp': (now - timedelta(seconds=340)).isoformat(),
            'files_changed': ['pyproject.toml'],
        },
        {
            'sha': 'sh4red1ib', 'commit_sha': 'sh4red1ib', 'author': 'dev-shared',
            'message': 'refactor(shared-lib): tax.round() takes 3 args now (breaking)',
            'timestamp': (now - timedelta(seconds=500)).isoformat(),
            'files_changed': ['shared_lib/tax.py'],
        },
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 84.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['ch3ckout1', 'sh4red1ib', 'shared-lib', 'shared_lib', 'tax', 'round'],
)
