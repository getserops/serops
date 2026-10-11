"""CD3 · Force-push rewrote history — logs mention SHAs no longer in the repo."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CD3'
TIER = 4


def run(ctx):
    now = datetime.now(timezone.utc)
    logs = [
        mk_log('INFO',  'app.startup: commit ghost001 (WAS: gh05t000 - force-pushed)', 300),
        mk_log('ERROR', 'checkout.tax: NoneType exception on VAT lines', 240),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 60),
    ]
    # Only the CURRENT commit exists (ghost001); the previous one was
    # rewritten away.
    code_changes = [{
        'sha': 'ghost001', 'commit_sha': 'ghost001', 'author': 'dev-bob',
        'message': 'chore: rebased tax refactor onto main',
        'timestamp': (now - timedelta(seconds=340)).isoformat(),
        'files_changed': ['services/checkout/tax.py'],
    }]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 42.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['ghost001', 'tax', 'nonetype', 'rebase', 'refactor'],
    # AI shouldn't hallucinate the rewritten SHA as still-present
    root_cause_does_not_contain=['gh05t000 caused'],
)
