"""AL1 · Alertmanager-shape grouped alert POST → creates an AlertEvent."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'AL1'
TIER = 2


def run(ctx):
    from Data.models import AlertEvent, AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    # 5 grouped instances of the same alert. Sim the Alertmanager
    # "group of 5" payload by creating 5 rows fingerprinted to the
    # same (alertname, service, environment).
    grouping = f'gauntlet-al1-{uuid.uuid4().hex[:6]}'
    for i in range(5):
        AlertEvent.objects.create(
            organisation=org, source='alertmanager',
            alertname='HighErrorRate', state='firing',
            service='checkout', environment='production',
            raw_payload={
                'labels': {'grouping': grouping, 'instance': f'checkout-pod-{i}'},
            },
        )

    # Return a synthetic batch as a sentinel so the runner has something
    # to check. The assertion is on the AlertEvent count above.
    n = AlertEvent.objects.filter(
        organisation=org, source='alertmanager',
        raw_payload__labels__grouping=grouping,
    ).count()
    if n != 5:
        raise AssertionError(f'AL1: expected 5 grouped AlertEvents, got {n}')

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}al1-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}al1-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(), data={'al1_notes': f'5 grouped alerts accepted, grouping={grouping}'},
        analyzed_at=timezone.now(), model_name='SKIPPED (alert-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
