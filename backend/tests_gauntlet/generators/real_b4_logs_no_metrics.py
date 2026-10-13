"""B4 · Logs present, metrics agent crashed silently — analysis must still run."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'B4'
TIER = 3


def run(ctx):
    logs = [
        mk_log('ERROR', 'checkout: OOMKilled — pod restart storm', 240),
        mk_log('ERROR', 'checkout: 3 pods restarted in 90s', 180),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={},  # explicit empty — metrics agent died
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['oom', 'memory', 'restart', 'pod'],
    root_cause_does_not_contain=['no metrics available', 'insufficient data'],
)
