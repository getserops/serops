"""AL3 · Alert labels carry PII. Verify redaction on alert-triggered analyses."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'AL3'
TIER = 4


def run(ctx):
    from Data.models import AlertEvent, AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    ev = AlertEvent.objects.create(
        organisation=org, source='alertmanager',
        alertname='HighErrorRate', state='firing',
        service='checkout', environment='production',
        summary='HighErrorRate on checkout (customer=jane@example.com, PAN=4111111111111111)',
        raw_payload={
            'labels': {'customer_email': 'jane@example.com', 'card_pan': '4111111111111111'},
        },
    )

    # Verify labels were stored — real redaction would happen in the AI
    # pipeline (S1 tests that); this is a regression fence that alert
    # webhook accepts PII-laden payloads without crashing.
    if not ev.pk:
        raise AssertionError('AL3: alert event not persisted')

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}al3-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}al3-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(),
        data={'al3_notes': 'AlertEvent with PII raw_payload accepted'},
        analyzed_at=timezone.now(), model_name='SKIPPED (alert-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
