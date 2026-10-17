"""SN2 · Sentinel must escalate a batch that LOOKS quiet.

Same benign baseline as SN1, but the batch contains ONE hidden CRITICAL
line: a real OOMKill on the checkout service. Sentinel must escalate
this via the 'new_error_pattern' trigger because the CRITICAL
fingerprint isn't in state.known_log_patterns.

Ai_skipped must be False. AI must run and produce at least one issue.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'SN2'
TIER = 0


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(level: str, msg: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def run(ctx):
    # Reuse SN1's helpers — same fixture setup, different payload.
    from tests_gauntlet.generators.real_sn1_quiet_correct import (
        _prime_sentinel_state, _set_active_mode,
    )
    from tests_gauntlet._core import create_batch, ensure_project

    ensure_project(ctx)
    _prime_sentinel_state(ctx)
    _set_active_mode(ctx.org_id, True)

    # Mostly quiet, but one hidden CRITICAL nobody's seen before.
    logs = [_log('INFO', f'health check pass — iteration {i}', 10 - i) for i in range(9)]
    logs.append(_log(
        'CRITICAL',
        'OOMKill: checkout pod (pid 2847) exceeded memory limit 512Mi during cart-flush',
        1,
    ))
    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={
            'memory': {'usage_percent': {'avg': 44.0}},  # near baseline — memory z-score won't fire
            'cpu': {'usage_percent': {'avg': 21.0}},
        },
    )


EXPECTATION = Expectation(
    sentinel_decision='alert',
    sentinel_triggers_contains=['new_error_pattern'],
    ai_skipped_expected=False,
    min_issues=1,
    root_cause_contains=['memory'],
    timed_out_ok=False,
)
