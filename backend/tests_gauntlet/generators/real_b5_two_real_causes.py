"""B5 · Memory pressure + bad deploy at same minute; both real, AI must surface both."""
from datetime import datetime, timedelta, timezone
from tests_gauntlet._core import Expectation, create_batch, mk_log

BATCH_ID = 'B5'
TIER = 3


def run(ctx):
    logs = [
        mk_log('INFO',  'app.startup: v2.1 ready · commit cafe1234', 300),
        mk_log('WARN',  'heap.usage: 88% (baseline 40%) — leak candidate', 240),
        mk_log('ERROR', 'checkout.tax: unhandled TypeError from commit cafe1234', 200),
        mk_log('WARN',  'heap.usage: 96% · full-gc pause 3800ms', 180),
        mk_log('ERROR', 'OOMKilled: checkout pid 2847', 150),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm', 60),
    ]
    code_changes = [{
        'sha': 'cafe1234', 'commit_sha': 'cafe1234',
        'author': 'dev-dana',
        'message': 'feat(checkout): new tax handler with in-memory cache',
        'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=320)).isoformat(),
        'files_changed': ['services/checkout/tax.py'],
    }]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 41.0, 'memory': {'usage_percent': {'avg': 92.0}}},
    )


EXPECTATION = Expectation(
    min_issues=2,  # both memory + tax deploy should surface as separate issues
    root_cause_contains_any=['cafe1234', 'tax', 'memory', 'oom', 'commit'],
)
