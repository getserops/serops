"""D1 · Three services named 'checkout' in three different projects.

An alert arrives with ``service=checkout`` and no project qualifier.
Three projects on the org each have a service by that name. The
resolver must pick the one with the most integration wiring (SCM +
CICD bindings) — the "real prod" project — not the empty seed shell.

Uses the wiring-score tiebreak shipped in PR-AUDIT5 (finding #5).

This generator doesn't create an AIAnalyzedBatch — it directly tests
the alert-resolution path by:
1. Provisioning 3 projects with same service name
2. Wiring one of them (the "real" one) with SCM + CICD bindings
3. Creating a synthetic AlertEvent and calling ``_resolve_alert_project``
4. Asserting the wired project won

Because it doesn't go through analyze_batch, the returned "batch id"
is a sentinel proving the assertion passed.
"""

from __future__ import annotations
from datetime import datetime, timezone
import uuid

from tests_gauntlet._core import Expectation, GAUNTLET_PREFIX

BATCH_ID = 'D1'
TIER = 1


def _make_projects(ctx):
    """Return (empty_shell, mid_wired, fully_wired) — 3 projects, all
    with a ``checkout`` service, different wiring levels."""
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService, SCMBinding, CICDBinding
    from providers.models import ProviderIntegration

    org = Organisations.objects.get(id=ctx.org_id)

    # Clean up any prior D1 projects so this run is deterministic
    Project.objects.filter(
        organisation=org, name__startswith='gauntlet-d1-',
    ).delete()

    integration, _ = ProviderIntegration.objects.get_or_create(
        organisation=org, name='gauntlet-d1-github',
        defaults={'provider_type': 'github', 'category': 'devops'},
    )

    # Use a unique service name so we don't collide with any other
    # 'checkout' services that already exist on this org from prior
    # audit / gauntlet runs. The alert we fire below targets this
    # exact name.
    svc_name = 'gauntlet-d1-svc'

    empty = Project.objects.create(organisation=org, name='gauntlet-d1-empty-shell')
    ProjectService.objects.create(project=empty, name=svc_name, status='Active')
    ProjectEnvironment.objects.create(project=empty, name='production', is_active=True)

    mid = Project.objects.create(organisation=org, name='gauntlet-d1-mid-wired')
    mid_service = ProjectService.objects.create(project=mid, name=svc_name, status='Active')
    ProjectEnvironment.objects.create(project=mid, name='production', is_active=True)
    SCMBinding.objects.create(
        project_service=mid_service, integration=integration,
        repository_id='mid-42',
    )

    real = Project.objects.create(organisation=org, name='gauntlet-d1-real-prod')
    real_service = ProjectService.objects.create(project=real, name=svc_name, status='Active')
    ProjectEnvironment.objects.create(project=real, name='production', is_active=True)
    SCMBinding.objects.create(
        project_service=real_service, integration=integration,
        repository_id='real-99',
    )
    CICDBinding.objects.create(
        project_service=real_service, integration=integration,
        binding_type='deploy', pipeline_id='deploy-checkout',
        pipeline_name='deploy-checkout',
    )
    return empty, mid, real, svc_name


def run(ctx):
    from Data.models import AlertEvent, AIAnalyzedBatch, Issue
    from Data.tasks import _resolve_alert_project
    from Organisations.models import Organisations
    from Projects.models import Project
    from django.utils import timezone as tz
    from tests_gauntlet._core import ensure_project

    ensure_project(ctx)
    empty, mid, real, svc_name = _make_projects(ctx)
    org = Organisations.objects.get(id=ctx.org_id)

    # Fire an alert that names the D1-specific service. Uses the unique
    # ``svc_name`` so pre-existing 'checkout' services from other test
    # runs don't compete with our fixture.
    event = AlertEvent.objects.create(
        organisation=org, source='alertmanager',
        alertname='HighErrorRate', state='firing',
        service=svc_name, environment='production',
    )
    picked = _resolve_alert_project(event)

    if picked is None:
        raise AssertionError('D1: resolver returned no project for a service-named alert')
    if picked.id != real.id:
        raise AssertionError(
            f'D1: resolver picked wrong project (id={picked.id} {picked.name!r}) — '
            f'expected fully-wired {real.name!r} (id={real.id})'
        )

    # Also verify the resolver would keep picking the wired one across
    # 5 repeats (stable, not lottery-y).
    for _ in range(5):
        again = _resolve_alert_project(event)
        if again.id != real.id:
            raise AssertionError('D1: resolver is non-deterministic')

    # Return a sentinel batch so the runner has something to report.
    # It carries no logs — the assertion above is the real test.
    project = Project.objects.get(id=ctx.project_id)
    sentinel_id = f'{GAUNTLET_PREFIX}d1-sentinel-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(
        batch_id__startswith=f'{GAUNTLET_PREFIX}d1-sentinel-',
    ).delete()
    b = AIAnalyzedBatch.objects.create(
        batch_id=sentinel_id, project=project, organisation=org,
        timestamp=tz.now(),
        data={'d1_notes': 'resolver picked correct project — no AI needed'},
        logs_analyzed=0,
        analyzed_at=tz.now(),
        model_name='SKIPPED (resolver-only test)',
    )
    return sentinel_id


EXPECTATION = Expectation(
    # No AI ran, no issues expected.
    max_issues=0,
    # Sentinel is never called since we bypass analyze_batch — this
    # generator's real assertion is inside ``run()``. If the assertion
    # fires, the runner reports "generator crashed".
    timed_out_ok=False,
)
