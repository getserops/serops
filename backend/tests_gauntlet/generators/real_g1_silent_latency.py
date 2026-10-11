"""G1 · No errors. p50 unchanged. p99 doubled. AI must still flag latency regression."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'G1'
TIER = 2


def run(ctx):
    logs = [
        mk_log('INFO', f'GET /api/checkout 200 · duration={340 + i*3}ms', 300 - i*3) for i in range(30)
    ]
    logs += [
        mk_log('WARN',  f'GET /api/checkout 200 · duration=4120ms · SLOW (p99)', 60),
        mk_log('WARN',  f'GET /api/checkout 200 · duration=4340ms · SLOW (p99)', 40),
        mk_log('ERROR', f'checkout SLO breach: p99 latency 4520ms exceeds 1000ms budget', 15),
        mk_log('ERROR', f'checkout SLO breach: p99 latency 4830ms exceeds 1000ms budget', 5),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={
            'error_rate_pct': 0.1,
            'p50_latency_ms': 340,
            'p95_latency_ms': 480,
            'p99_latency_ms': 4400,
        },
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['latency', 'slow', 'p99', 'degrad', 'regression', 'tail'],
)
