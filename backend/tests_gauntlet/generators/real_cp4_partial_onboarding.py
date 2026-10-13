"""CP4 · Org has logs + metrics but no CI/CD wired. Don't blame missing commits."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CP4'
TIER = 3


def run(ctx):
    logs = [
        mk_log('ERROR', 'redis.pool: connection refused to redis:6379', 240),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 76.0},
        code_changes=[],  # explicit — CI/CD not wired
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
    # Common failure: AI invents "a recent deploy caused this" when
    # no deploy info exists at all.
    root_cause_does_not_contain=['recent deploy', 'commit', 'no commits available'],
)
