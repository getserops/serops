"""CD1 · Squash merge of 30-commit feature branch. AI blames the squash or the code path."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CD1'
TIER = 3

_SQUASH_SHA = '5qua5h001'


def run(ctx):
    now = datetime.now(timezone.utc)
    logs = [
        mk_log('INFO',  f'app.startup: v3.0 · squash-merge commit {_SQUASH_SHA} (was 30 commits)', 300),
        mk_log('ERROR', 'checkout.session: NoneType has no attribute cart_id', 240),
        mk_log('ERROR', 'checkout.session: 47 NPE in 5 min · post-deploy', 180),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 60),
    ]
    commits = [{
        'sha': _SQUASH_SHA, 'commit_sha': _SQUASH_SHA, 'author': 'dev-emma',
        'message': (
            'Merge PR #472: session-store rewrite\n\n'
            'Squashes 30 commits touching services/checkout/session/*.py'
        ),
        'timestamp': (now - timedelta(seconds=340)).isoformat(),
        'files_changed': ['services/checkout/session/api.py', 'services/checkout/session/store.py'],
    }]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=commits,
        metrics_summary={'error_rate_pct': 47.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=[_SQUASH_SHA, 'session', 'squash', 'nonetype', 'npe', 'rewrite', 'merge'],
)
