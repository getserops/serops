"""MT3 · Suspended-org batch — org may or may not have a suspend field; regression fence."""
import uuid
from tests_gauntlet._core import (
    Expectation, GAUNTLET_PREFIX, create_batch, mk_log, wait_for_analysis,
)

BATCH_ID = 'MT3'
TIER = 4


def _snapshot_and_suspend(org):
    """Suspend the org via best-effort field discovery. Returns restore fn."""
    def _try(attr, val):
        if hasattr(org, attr):
            prev = getattr(org, attr)
            setattr(org, attr, val)
            org.save(update_fields=[attr])
            return (attr, prev)
        return None

    changes = []
    for attr, val in (('is_suspended', True), ('is_active', False),
                      ('subscription_status', 'suspended')):
        c = _try(attr, val)
        if c:
            changes.append(c)
    return changes


def _restore(org, changes):
    for attr, prev in changes:
        setattr(org, attr, prev)
    if changes:
        org.save(update_fields=[c[0] for c in changes])


def run(ctx):
    from Organisations.models import Organisations
    from Data.models import AIAnalyzedBatch
    org = Organisations.objects.get(id=ctx.org_id)
    changes = _snapshot_and_suspend(org)
    try:
        bid = create_batch(
            ctx, short_name=BATCH_ID.lower(),
            logs=[mk_log('ERROR', 'redis.pool: connection refused', 60)],
            metrics_summary={'error_rate_pct': 78.0},
        )
        # Either the batch completes (no suspend enforcement yet) or
        # it fails gracefully — anti-goal is silent hang.
        summary = wait_for_analysis(bid, timeout=120)
        if summary.get('timed_out'):
            raise AssertionError('MT3: suspended-org batch hung — no analyzed_at, no ai_skipped')
    finally:
        _restore(org, changes)
    return bid


EXPECTATION = Expectation(
    # We tolerate either outcome — the assertion in run() catches hangs.
    timed_out_ok=False,
)
