"""G2 · Silent data corruption — writes succeed, reads return wrong values on 3%."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'G2'
TIER = 3


def run(ctx):
    logs = [
        mk_log('WARN',  'checkout.audit: cart total mismatch on read for cart c-8471 (expected 42.99, got 12.99)', 300),
        mk_log('WARN',  'checkout.audit: cart total mismatch on read for cart c-8492 (expected 89.50, got 89.05)', 240),
        mk_log('ERROR', 'checkout.audit: 47 mismatches in 15 min — 3.2% of cart reads', 180),
        mk_log('ERROR', 'checkout: postgres replica lag 14s · reads from replica returning stale data', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 0.5},  # no obvious error rate spike
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['replica', 'lag', 'stale', 'corrupt', 'mismatch', 'postgres'],
)
