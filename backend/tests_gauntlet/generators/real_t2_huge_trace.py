"""T2 · Large trace (500 spans) — memory + correlation-engine cap holds."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'T2'
TIER = 4


def run(ctx):
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from traces.models import Span, Trace
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)
    now = timezone.now()

    trace_id = uuid.uuid4().hex  # 32 chars
    trace = Trace.objects.create(
        organisation=org, trace_id=trace_id,
        root_service_name='checkout',
        root_operation='POST /checkout',
        start_time=now, end_time=now, duration_ms=42,
        span_count=500, error_span_count=3,
    )
    # 500 spans — bulk create for speed
    root = uuid.uuid4().hex[:16]
    Span.objects.create(
        trace=trace, span_id=root, parent_span_id='',  # root span
        service_name='checkout', operation_name='POST /checkout',
        start_time=now, end_time=now, duration_ms=42,
    )
    to_create = []
    for i in range(499):
        to_create.append(Span(
            trace=trace, span_id=uuid.uuid4().hex[:16],
            parent_span_id=root,
            service_name='checkout' if i % 3 else 'redis',
            operation_name=f'work-{i}',
            start_time=now, end_time=now, duration_ms=1,
        ))
    Span.objects.bulk_create(to_create, batch_size=100)

    if Span.objects.filter(trace=trace).count() != 500:
        raise AssertionError('T2: bulk_create did not produce 500 spans')

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}t2-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}t2-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=now, data={'trace_ids': [trace_id], 'span_count': 500},
        analyzed_at=now, model_name='SKIPPED (trace-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
