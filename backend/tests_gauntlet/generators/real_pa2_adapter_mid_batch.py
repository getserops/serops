"""PA2 · Simulated adapter fail mid-batch — partial data annotated cleanly."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'PA2'
TIER = 4


def run(ctx):
    logs = [
        mk_log('ERROR', 'redis.pool: connection refused', 240),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        # Explicit annotation that ingest was partial
        extra_data={'ingest_partial': True, 'ingest_error': 'Loki 502 mid-fetch'},
        metrics_summary={'error_rate_pct': 78.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
)
