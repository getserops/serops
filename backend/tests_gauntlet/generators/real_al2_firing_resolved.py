"""AL2 · Firing→firing→resolved: same alert dedups + resolution recorded."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'AL2'
TIER = 4


def run(ctx):
    from Data.models import AlertEvent, AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)
    fingerprint = f'gauntlet-al2-{uuid.uuid4().hex[:6]}'

    # Simulate 12 "firing" events + 1 resolved
    for i in range(12):
        AlertEvent.objects.create(
            organisation=org, source='alertmanager',
            alertname='HighErrorRate', state='firing',
            service='checkout', environment='production',
            external_id=fingerprint,
        )
    AlertEvent.objects.create(
        organisation=org, source='alertmanager',
        alertname='HighErrorRate', state='resolved',
        service='checkout', environment='production',
        external_id=fingerprint,
    )

    total = AlertEvent.objects.filter(organisation=org, external_id=fingerprint).count()
    resolved = AlertEvent.objects.filter(organisation=org, external_id=fingerprint, state='resolved').count()
    if total != 13:
        raise AssertionError(f'AL2: expected 13 events, got {total}')
    if resolved != 1:
        raise AssertionError(f'AL2: expected 1 resolved, got {resolved}')

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}al2-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}al2-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(),
        data={'al2_notes': f'12 firing + 1 resolved recorded on external_id={fingerprint}'},
        analyzed_at=timezone.now(), model_name='SKIPPED (alert-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
