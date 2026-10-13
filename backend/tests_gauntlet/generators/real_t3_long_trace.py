"""T3 · Long trace spanning multiple batch windows. Cross-batch reference survives."""
import uuid
from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX, ensure_project

BATCH_ID = 'T3'
TIER = 4


def run(ctx):
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    from traces.models import Span, Trace
    from django.utils import timezone
    from datetime import timedelta

    ensure_project(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    start = timezone.now() - timedelta(hours=4)
    end = timezone.now()
    trace_id = uuid.uuid4().hex
    trace = Trace.objects.create(
        organisation=org, trace_id=trace_id,
        root_service_name='batch-job',
        root_operation='nightly-report',
        start_time=start, end_time=end,
        duration_ms=int((end - start).total_seconds() * 1000),
        span_count=3, error_span_count=1,
    )
    Span.objects.create(
        trace=trace, span_id=uuid.uuid4().hex[:16], parent_span_id='',  # root
        service_name='batch-job', operation_name='nightly-report',
        start_time=start, end_time=end, duration_ms=trace.duration_ms,
        status_code='ERROR', status_message='timeout after 4h',
    )

    proj = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}t3-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(batch_id__startswith=f'{GAUNTLET_PREFIX}t3-sentinel-').delete()
    AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=proj, organisation=org,
        timestamp=timezone.now(),
        data={'trace_ids': [trace_id], 'trace_duration_hours': 4},
        analyzed_at=timezone.now(), model_name='SKIPPED (trace-only test)',
        logs_analyzed=0,
    )
    return sentinel_id


EXPECTATION = Expectation(max_issues=0)
