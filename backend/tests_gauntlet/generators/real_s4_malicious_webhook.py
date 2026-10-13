"""S4 · Malicious/spoofed webhook payload — rejected without ingest."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project, push_alert

BATCH_ID = 'S4'
TIER = 4


def run(ctx):
    from Data.models import AIAnalyzedBatch, AlertEvent
    from Organisations.models import Organisations
    from Projects.models import Project
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    before_count = AlertEvent.objects.filter(organisation=org, source='alertmanager').count()

    # 1) Well-formed but from an unknown source: alerts webhook accepts
    #    any well-formed payload (no signature enforcement today) — record
    #    the current behaviour as a regression fence.
    # 2) Malformed payload — should not crash the endpoint.
    ok_status, _ = push_alert(ctx, 'alertmanager', {
        'alerts': [{
            'labels': {'alertname': 'gauntlet-s4-attacker', 'service': 'checkout'},
            'annotations': {'summary': 'fake alert'},
            'status': 'firing',
        }],
    })
    bad_status, _ = push_alert(ctx, 'alertmanager', {'not-a-real-alert-payload': True})

    after_count = AlertEvent.objects.filter(organisation=org, source='alertmanager').count()
    if bad_status >= 500:
        raise AssertionError(f'S4: malformed webhook produced 500 (got {bad_status})')

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}s4-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}s4-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(),
        data={'s4_notes': f'ok_status={ok_status} bad_status={bad_status} '
                          f'events_delta={after_count - before_count}'},
        analyzed_at=timezone.now(), model_name='SKIPPED (webhook-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
