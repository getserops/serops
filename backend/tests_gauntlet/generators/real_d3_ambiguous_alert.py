"""D3 · Alert names service=api but 4 projects have an 'api' service."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'D3'
TIER = 3


def run(ctx):
    from Data.models import AlertEvent, AIAnalyzedBatch
    from Data.tasks import _resolve_alert_project
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService, SCMBinding, CICDBinding
    from providers.models import ProviderIntegration
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    Project.objects.filter(organisation=org, name__startswith='gauntlet-d3-').delete()
    integration, _ = ProviderIntegration.objects.get_or_create(
        organisation=org, name='gauntlet-d3-gh',
        defaults={'provider_type': 'github', 'category': 'devops'},
    )

    # 4 projects each with a 'gauntlet-d3-api' service; last one is best-wired
    svc_name = 'gauntlet-d3-api'
    for i, name in enumerate(('empty1', 'empty2', 'mid', 'real')):
        p = Project.objects.create(organisation=org, name=f'gauntlet-d3-{name}')
        s = ProjectService.objects.create(project=p, name=svc_name, status='Active')
        ProjectEnvironment.objects.create(project=p, name='production', is_active=True)
        if name in ('mid', 'real'):
            SCMBinding.objects.create(
                project_service=s, integration=integration, repository_id=f'r{i}')
        if name == 'real':
            CICDBinding.objects.create(
                project_service=s, integration=integration,
                binding_type='deploy', pipeline_id=f'p{i}', pipeline_name=f'pipe{i}')

    real = Project.objects.get(organisation=org, name='gauntlet-d3-real')
    event = AlertEvent.objects.create(
        organisation=org, source='alertmanager',
        alertname='HighErrorRate', state='firing',
        service=svc_name, environment='production',
    )
    picked = _resolve_alert_project(event)
    if picked is None or picked.id != real.id:
        raise AssertionError(
            f'D3: expected real-prod project id={real.id}, got id={getattr(picked, "id", None)}'
        )

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}d3-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}d3-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(),
        data={'d3_notes': 'ambiguous alert resolved to best-wired project'},
        analyzed_at=timezone.now(), model_name='SKIPPED (resolver-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
