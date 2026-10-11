"""D2 · Noisy neighbor: 3 orgs have batches in the same window, only one has a real issue."""
import uuid
from tests_gauntlet._core import (
    Expectation, GAUNTLET_PREFIX, create_batch, mk_log,
)

BATCH_ID = 'D2'
TIER = 2

_NEIGHBOR_SIG = 'noise-tenant-N-signature'


def _ensure_neighbor_org(name):
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService
    org, _ = Organisations.objects.get_or_create(
        name=name, defaults={'website': f'https://{name}.local'},
    )
    proj, _ = Project.objects.get_or_create(
        organisation=org, name='noise-svc',
        defaults={'description': 'D2 neighbor fixture'},
    )
    ProjectService.objects.get_or_create(project=proj, name='noise', defaults={'status': 'Active'})
    ProjectEnvironment.objects.get_or_create(project=proj, name='production', defaults={'is_active': True})
    return org, proj


def run(ctx):
    from Data.models import AIAnalyzedBatch
    from django.utils import timezone
    from ai_model.tasks import analyze_batch

    # Two noise batches on two different neighbor orgs
    for name in ('gauntlet-d2-neighbor-a', 'gauntlet-d2-neighbor-b'):
        org, proj = _ensure_neighbor_org(name)
        bid = f'{GAUNTLET_PREFIX}d2-noise-{uuid.uuid4().hex[:8]}'
        AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}d2-noise-').filter(organisation=org).delete()
        b = AIAnalyzedBatch.objects.create(
            batch_id=bid, project=proj, organisation=org,
            timestamp=timezone.now(),
            data={'logs': [
                {'_id': 'n1', '_source': dict(mk_log('INFO', f'{_NEIGHBOR_SIG} noise A', 60,
                                                    service='noise', organisation=name, project='noise-svc'))},
            ]},
            logs_analyzed=1,
        )
        analyze_batch.delay(bid)

    # Real batch on ctx.org — no neighbor signature
    logs = [
        mk_log('ERROR', 'redis.pool: connection refused', 240),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 74.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
    root_cause_does_not_contain=[_NEIGHBOR_SIG, 'neighbor', 'tenant-N'],
)
