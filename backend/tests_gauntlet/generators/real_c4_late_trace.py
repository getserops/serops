"""C4 · Late-arriving trace carries the true root cause (postgres lock)."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'C4'
TIER = 3


def run(ctx):
    from datetime import datetime, timezone
    logs = [
        mk_log('ERROR', 'checkout: 502 upstream timeout', 180),
        mk_log('ERROR', 'checkout: circuit breaker OPEN', 60),
    ]
    now_iso = datetime.now(timezone.utc).isoformat()
    # PR-TRACE1 (2026-09-21): trace snapshot must match
    # ``ai_model.trace_context._from_native``'s dict shape so
    # ``_read_snapshot`` returns it and the prompt formatter renders
    # the Distributed Traces section. Keys with the wrong shape are
    # silently ignored by the reader.
    trace_snapshot = {
        'source': 'otlp',
        'span_count': 12,
        'error_span_count': 3,
        'trace_count': 1,
        'services_touched': ['postgres-primary', 'checkout'],
        'top_slow': [{
            'trace_id': 'aabbccddeeff00112233445566778899',
            'service_name': 'postgres-primary',
            'operation_name': 'SELECT orders WHERE user_id=$1',
            'duration_ms': 8420,
            'status_code': 'ERROR',
            'start_time': now_iso,
        }],
        'top_errors': [{
            'trace_id': 'aabbccddeeff00112233445566778899',
            'service_name': 'postgres-primary',
            'operation_name': 'SELECT orders WHERE user_id=$1',
            'status_message': 'lock_wait_timeout on relation orders',
            'duration_ms': 8420,
            'start_time': now_iso,
        }],
    }
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        extra_data={'traces': trace_snapshot},
        metrics_summary={'error_rate_pct': 22.0, 'p95_latency_ms': 8400},
    )


EXPECTATION = Expectation(
    min_issues=1,
    # With trace snapshot in the right shape, the AI now sees the
    # postgres slow query as evidence and should name it (not just
    # the surface "upstream timeout"). Keeping the alternative
    # "upstream/dependency" keywords as fallback in case the AI
    # phrases the same fact differently.
    root_cause_contains_any=[
        'postgres', 'lock', 'query', 'orders', 'database', 'sql',
        'upstream', 'dependency', 'downstream',
    ],
)
