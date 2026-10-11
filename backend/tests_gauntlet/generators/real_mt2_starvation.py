"""MT2 · Noisy neighbor bursts. Verify the target batch still runs (no starvation)."""
import uuid
from tests_gauntlet._core import (
    Expectation, GAUNTLET_PREFIX, create_batch, mk_log, wait_for_analysis,
)

BATCH_ID = 'MT2'
TIER = 4


def run(ctx):
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService
    from ai_model.tasks import analyze_batch
    from django.utils import timezone

    # Second org — busy neighbour
    neighbour, _ = Organisations.objects.get_or_create(
        name='gauntlet-mt2-neighbour',
        defaults={'website': 'https://gauntlet-mt2-neighbour.local'},
    )
    proj, _ = Project.objects.get_or_create(
        organisation=neighbour, name='mt2-noise',
        defaults={'description': 'MT2 starvation fixture'},
    )
    ProjectService.objects.get_or_create(project=proj, name='noise', defaults={'status': 'Active'})
    ProjectEnvironment.objects.get_or_create(project=proj, name='production', defaults={'is_active': True})

    # Queue 20 noise batches for the neighbour
    for i in range(20):
        bid = f'{GAUNTLET_PREFIX}mt2-noise-{i}-{uuid.uuid4().hex[:6]}'
        AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}mt2-noise-{i}-').delete()
        b = AIAnalyzedBatch.objects.create(
            batch_id=bid, project=proj, organisation=neighbour,
            timestamp=timezone.now(),
            data={'logs': [{'_id': str(i), '_source': dict(mk_log('INFO', f'noise {i}', 30,
                          service='noise', organisation='gauntlet-mt2-neighbour', project='mt2-noise'))}]},
            logs_analyzed=1,
        )
        analyze_batch.delay(bid)

    # Then our real batch — it should still run in reasonable time
    logs = [
        mk_log('ERROR', 'redis.pool: connection refused', 240),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    real_bid = create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                            metrics_summary={'error_rate_pct': 78.0})
    summary = wait_for_analysis(real_bid, timeout=180)
    if summary.get('timed_out'):
        raise AssertionError('MT2: neighbour batches starved our real batch')
    return real_bid


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
)
