"""SN3 · Sentinel shadow mode — AI runs but decision is recorded, ai_skipped stays false."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'SN3'
TIER = 4


def run(ctx):
    from tests_gauntlet.generators.real_sn1_quiet_correct import (
        _prime_sentinel_state, _set_active_mode,
    )
    from tests_gauntlet._core import ensure_project

    ensure_project(ctx)
    _prime_sentinel_state(ctx)
    _set_active_mode(ctx.org_id, False)   # shadow (active_mode=False)

    logs = [mk_log('INFO', f'heartbeat {i}', 300 - i*30) for i in range(10)]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'memory': {'usage_percent': {'avg': 41.0}}})


EXPECTATION = Expectation(
    # Shadow mode: Sentinel decides but never skips AI
    sentinel_decision='quiet',
    ai_skipped_expected=False,
)
