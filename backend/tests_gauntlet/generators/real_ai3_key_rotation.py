"""AI3 · Key rotated mid-batch — same graceful-failure shape as AI2."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'AI3'
TIER = 4


def _rotate_key(org_id):
    """Change the api_key value on the org's active API keys. Returns
    the snapshot to restore. Simulates the operator rotating credentials
    between when the batch queued and when analyze_batch runs."""
    from org_settings.models import OrganisationAPIKey
    snapshots = []
    for k in OrganisationAPIKey.objects.filter(organisation_id=org_id, is_active=True):
        snapshots.append((k.id, k.api_key))
        k.api_key = 'gAAAAA' + 'X' * 40  # decrypt-fail shape
        k.save(update_fields=['api_key'])
    return snapshots


def _restore(snaps):
    from org_settings.models import OrganisationAPIKey
    for kid, prev in snaps:
        k = OrganisationAPIKey.objects.get(id=kid)
        k.api_key = prev
        k.save(update_fields=['api_key'])


def run(ctx):
    from tests_gauntlet._core import wait_for_analysis
    from Data.models import AIAnalyzedBatch, Issue
    snap = _rotate_key(ctx.org_id)
    try:
        bid = create_batch(ctx, short_name=BATCH_ID.lower(),
                           logs=[mk_log('ERROR', 'redis.pool: connection refused', 60)],
                           metrics_summary={'error_rate_pct': 88.0})
        summary = wait_for_analysis(bid, timeout=60)
        if Issue.objects.filter(batch__batch_id=bid).count() > 0:
            raise AssertionError('AI3: ghost issues persisted despite AI failure')
        b = AIAnalyzedBatch.objects.get(batch_id=bid)
        if b.analyzed_at is None and not getattr(b, 'ai_skipped', False):
            raise AssertionError('AI3: batch has no analyzed_at and no ai_skipped — infinite spinner')
    finally:
        _restore(snap)
    return bid


EXPECTATION = Expectation(max_issues=0)
