"""CP2 · Rare inverse: traces only, no logs. RCA still produces a coherent narrative."""
from tests_gauntlet._core import Expectation, create_batch
BATCH_ID = 'CP2'
TIER = 4


def run(ctx):
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=[],
        traces=[{
            'trace_id': 'aa11bb22cc33dd44ee55ff66aabbccdd',
            'root_service': 'postgres-primary',
            'root_operation': 'SELECT orders WHERE user_id=$1',
            'duration_ms': 8420,
            'status_code': 'ERROR',
            'error_message': 'lock_wait_timeout on relation orders',
        }],
        metrics_summary={'p95_latency_ms': 8400, 'error_rate_pct': 22.0},
    )


EXPECTATION = Expectation(
    # Prompt must not scapegoat missing logs
    max_issues=1,
    root_cause_does_not_contain=['no logs available', 'insufficient log data'],
)
