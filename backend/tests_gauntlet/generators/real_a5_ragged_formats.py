"""A5 · Mixed log formats within one batch (JSON / syslog / plaintext / key=value)."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'A5'
TIER = 2


def run(ctx):
    logs = [
        mk_log('ERROR', '{"ts":"now","svc":"checkout","level":"error","msg":"redis conn refused","code":"ECONNREFUSED"}', 250),
        mk_log('ERROR', '<11>Sep 20 15:00:12 checkout-01 kernel: TCP: connection to redis:6379 refused', 220),
        mk_log('ERROR', 'checkout redis pool exhausted after 40 refusals', 190),
        mk_log('ERROR', 'level=error service=checkout target=redis:6379 error=connection_refused count=40', 160),
        mk_log('WARN',  '{"ts":"now","svc":"checkout","level":"warn","msg":"circuit breaker OPEN"}', 130),
        mk_log('ERROR', 'checkout returning 500 on POST /checkout/confirm', 60),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 62.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection', 'circuit'],
)
