"""CD4 · Merge commit + real commit — AI can blame the merge or the constituent."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CD4'
TIER = 4


def run(ctx):
    now = datetime.now(timezone.utc)
    logs = [
        mk_log('INFO',  'app.startup: merged PR #712 (merge sha mrg99999) with 8 commits', 300),
        mk_log('ERROR', 'checkout.session: KeyError \'user_id\' — new schema mismatch', 240),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 60),
    ]
    code_changes = [
        {
            'sha': 'mrg99999', 'commit_sha': 'mrg99999', 'author': 'gh-actions',
            'message': 'Merge pull request #712 from feature/session-schema',
            'timestamp': (now - timedelta(seconds=340)).isoformat(),
            'files_changed': ['services/checkout/session.py'],
        },
        {
            'sha': 'realbug1', 'commit_sha': 'realbug1', 'author': 'dev-carol',
            'message': 'refactor(session): rename user_id → account_id (breaking)',
            'timestamp': (now - timedelta(seconds=800)).isoformat(),
            'files_changed': ['services/checkout/session.py'],
        },
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 46.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=[
        'mrg99999', 'realbug1', 'session', 'user_id', 'account_id',
        'rename', 'schema', 'merge',
    ],
)
