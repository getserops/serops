"""PA3 · Malformed provider response — parser hardens, doesn't crash."""
from tests_gauntlet._core import Expectation, create_batch
BATCH_ID = 'PA3'
TIER = 4


def run(ctx):
    # Feed logs with malformed _source shapes to test parser resilience
    malformed_logs = [
        {'_id': 'm1', '_source': {'level': 'ERROR', 'message': 'redis conn refused',
                                   'service_name': None,  # null in a required-ish field
                                   'labels': {'k': ['nested', {'weird': True}]}}},
        {'_id': 'm2', '_source': {'level': 'ERROR',
                                   # missing message entirely
                                   '@timestamp': 'not-a-date'}},
        {'_id': 'm3'},  # no _source at all
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=malformed_logs,
        metrics_summary={'error_rate_pct': 55.0},
    )


EXPECTATION = Expectation(
    # No crash requirement is implicit — if the batch reached the runner
    # it means analyze_batch survived the malformed shapes.
    timed_out_ok=False,
)
