"""T1 · Orphan span — a trace where child's parent_id points at nothing. Must not crash."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'T1'
TIER = 2


def run(ctx):
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from traces.models import Span, Trace
    from django.utils import timezone

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    trace_id = uuid.uuid4().hex  # 32 hex chars — model cap is 32
    now = timezone.now()
    trace = Trace.objects.create(
        organisation=org, trace_id=trace_id,
        root_service_name='checkout',
        root_operation='POST /checkout',
        start_time=now,
        end_time=now,
        duration_ms=1,
        span_count=1,
        error_span_count=0,
    )
    # A single span whose parent_id refers to a span we never ingest.
    Span.objects.create(
        trace=trace, span_id=uuid.uuid4().hex[:16],
        parent_span_id='dead' + uuid.uuid4().hex[:12],  # orphan
        service_name='checkout',
        operation_name='POST /checkout',
        start_time=now,
        end_time=now,
        duration_ms=1,
        status_code='OK',
    )

    # Verify the correlation engine can handle it: run correlate over a
    # batch that references this trace.
    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}t1-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}t1-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(), data={'trace_ids': [trace_id]},
        analyzed_at=timezone.now(), model_name='SKIPPED (trace-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
