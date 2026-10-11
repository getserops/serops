"""CP3 · Brand-new project's very first batch — no history, no known fingerprints."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, create_batch, mk_log

BATCH_ID = 'CP3'
TIER = 2


def run(ctx):
    from Data.models import AIAnalyzedBatch, ProjectEnvironmentState
    from Projects.models import Project, ProjectService, ProjectEnvironment
    from Organisations.models import Organisations

    # Fresh single-use project on ctx.org so Sentinel sees "first batch"
    org = Organisations.objects.get(id=ctx.org_id)
    proj_name = f'gauntlet-cp3-fresh-{uuid.uuid4().hex[:6]}'
    proj = Project.objects.create(organisation=org, name=proj_name)
    ProjectService.objects.create(project=proj, name='checkout', status='Active')
    ProjectEnvironment.objects.create(project=proj, name='production', is_active=True)

    original_project = ctx.project_id
    ctx.project_id = proj.id
    try:
        logs = [
            mk_log('ERROR', 'redis.pool: connection refused to redis:6379', 200,
                   project=proj_name),
            mk_log('ERROR', 'checkout: rejecting new sessions', 60,
                   project=proj_name),
        ]
        return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                            metrics_summary={'error_rate_pct': 70.0})
    finally:
        ctx.project_id = original_project


EXPECTATION = Expectation(
    min_issues=1,
    # First-batch sentinel decision — analysis runs. Cold-start must produce
    # a real narrative, not "insufficient history".
    root_cause_contains_any=['redis', 'connection', 'refused'],
    sentinel_decision='first',
)
