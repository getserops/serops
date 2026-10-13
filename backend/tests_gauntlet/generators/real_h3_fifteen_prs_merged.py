"""H3 · 15 PRs merged in the last 2 hours; which one caused this? Rank, don't recency-pick."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log

BATCH_ID = 'H3'
TIER = 2

_CULPRIT = 'b4dc0de0'


def run(ctx):
    now = datetime.now(timezone.utc)
    # 15 commits over 2 h. Only #7 (b4dc0de0) actually touches checkout tax logic.
    commits = []
    for i in range(15):
        commits.append({
            'sha': f'c0mmit{i:02d}',
            'commit_sha': f'c0mmit{i:02d}',
            'author': f'dev-{chr(97+i)}',
            'message': f'refactor(subsystem-{i}): unrelated tidy #{i}',
            'timestamp': (now - timedelta(minutes=120 - i*8)).isoformat(),
            'files_changed': [f'services/subsystem-{i}/misc.py'],
        })
    commits[7] = {
        'sha': _CULPRIT, 'commit_sha': _CULPRIT, 'author': 'dev-h',
        'message': 'feat(checkout): change tax rounding rule for VAT',
        'timestamp': (now - timedelta(minutes=64)).isoformat(),
        'files_changed': ['services/checkout/tax.py'],
    }
    logs = [
        mk_log('ERROR', 'checkout.tax: AssertionError: tax total mismatch by 1c on VAT rounding', 55),
        mk_log('ERROR', 'checkout.tax: AssertionError: tax total mismatch by 3c on VAT rounding', 40),
        mk_log('ERROR', 'checkout.tax: 47 tax assertions failed in 5 min · returning HTTP 500', 30),
        mk_log('ERROR', 'checkout: POST /checkout/confirm 500 · tax rounding rejected downstream', 15),
        mk_log('ERROR', 'checkout: 100% failure on cart totals with VAT lines', 5),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs, code_changes=commits,
        metrics_summary={'error_rate_pct': 18.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    # The AI should blame the tax-touching commit OR the tax subsystem itself
    root_cause_contains_any=[_CULPRIT, 'tax', 'rounding', 'vat'],
)
