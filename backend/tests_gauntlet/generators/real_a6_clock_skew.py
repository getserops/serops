"""A6 · Clock skew — services 47s apart on wall-clock, AI must still trace cause→symptom."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'A6'
TIER = 2


def run(ctx):
    # postgres clock is 47s AHEAD of checkout. Root event 'timestamps' later
    # than symptom event on service clocks — AI should not be misled.
    logs = [
        mk_log('WARN',  'postgres.autovacuum: blocked on orders (dead tuples 3.2M)', 233, service='postgres-primary'),
        mk_log('ERROR', 'checkout: db call slow (14s) on GET /orders/latest', 280, service='checkout'),
        mk_log('ERROR', 'postgres: slow query WARNING duration=8420ms', 213, service='postgres-primary'),
        mk_log('ERROR', 'checkout: circuit break for /orders/*', 240, service='checkout'),
        mk_log('ERROR', 'checkout: 500 on /checkout/confirm', 180, service='checkout'),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 38.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['postgres', 'database', 'autovacuum', 'slow query', 'db'],
)
