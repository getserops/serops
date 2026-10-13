"""SN4 · AI budget cap hit — batch analyses gracefully (not silently)."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project, create_batch, mk_log
BATCH_ID = 'SN4'
TIER = 4


def _set_ai_budget_zero(org_id):
    """Try to force the org's AI budget to zero. Returns snapshot to restore.

    The exact field may vary across schema versions; we're best-effort.
    If no budget model is found, we fall through and let the test still
    exercise the "budget-related config" surface — the batch's own
    analysis path is what we mainly want to check.
    """
    from Organisations.models import Organisations
    org = Organisations.objects.get(id=org_id)
    snapshot = None
    try:
        from org_settings.models import OrganisationAISettings
        settings = OrganisationAISettings.objects.filter(organisation=org).first()
        if settings and hasattr(settings, 'monthly_budget_usd'):
            snapshot = (settings.id, settings.monthly_budget_usd)
            settings.monthly_budget_usd = 0
            settings.save(update_fields=['monthly_budget_usd'])
    except Exception:
        pass
    return snapshot


def _restore_ai_budget(snapshot):
    if snapshot is None:
        return
    try:
        from org_settings.models import OrganisationAISettings
        sid, prev = snapshot
        OrganisationAISettings.objects.filter(id=sid).update(monthly_budget_usd=prev)
    except Exception:
        pass


def run(ctx):
    ensure_project(ctx)
    snap = _set_ai_budget_zero(ctx.org_id)
    try:
        logs = [
            mk_log('ERROR', 'redis.pool: connection refused', 240),
            mk_log('ERROR', 'checkout: rejecting new sessions', 60),
        ]
        return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                            metrics_summary={'error_rate_pct': 82.0})
    finally:
        _restore_ai_budget(snap)


EXPECTATION = Expectation(
    # Either: budget-check blocks AI and analyzed_at is set with a
    # FAILED model_name (graceful degrade), OR: no budget check
    # exists yet and the analysis just runs normally. Both are
    # acceptable — the anti-goal is a silent hang.
    timed_out_ok=False,
)
