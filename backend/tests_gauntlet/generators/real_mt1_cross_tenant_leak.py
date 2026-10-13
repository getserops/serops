"""MT1 · Cross-tenant leak.

Two orgs analyse batches in the same window with same-shaped content
(both mention 'checkout'). Verify that org A's ``AIAnalyzedBatch`` +
``Issue`` records never reference org B's distinctive signature, and
vice versa.

Setup:
* Org A = ctx.org_id (default 1, "Acme Cloud"). Batch A has a distinctive
  string "acme-alpha-signature-XYZ".
* Org B is auto-created as "gauntlet-mt1-tenant-b". Batch B has
  "beta-signature-QRS".

After both analyse, we assert the RETURNED batch (org A) does not carry
the org-B signature. The generator also runs a raw DB check (below)
proving that ``Issue.objects.filter(organisation=orgB)`` does not
contain org A's signature.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation, create_batch, wait_for_analysis

BATCH_ID = 'MT1'
TIER = 0

_ACME_SIG = 'acme-alpha-signature-XYZ'
_BETA_SIG = 'beta-signature-QRS'


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(level: str, msg: str, org_name: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': org_name,
        'project_name': 'checkout',
        'environment': 'production',
    }


def _ensure_second_org():
    """Create/reuse a second org for isolation testing. Returns its id."""
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService
    org, _ = Organisations.objects.get_or_create(
        name='gauntlet-mt1-tenant-b',
        defaults={'website': 'https://gauntlet-mt1-tenant-b.local'},
    )
    proj, _ = Project.objects.get_or_create(
        organisation=org, name='checkout-b',
        defaults={'description': 'MT1 tenant-B fixture'},
    )
    ProjectService.objects.get_or_create(
        project=proj, name='checkout', defaults={'status': 'Active'},
    )
    ProjectEnvironment.objects.get_or_create(
        project=proj, name='production', defaults={'is_active': True},
    )
    return org.id, proj.id


def run(ctx):
    from Data.models import AIAnalyzedBatch, Issue
    from Organisations.models import Organisations
    from Projects.models import Project
    from ai_model.tasks import analyze_batch
    from django.utils import timezone

    # Ensure the org-B fixture
    org_b_id, proj_b_id = _ensure_second_org()

    # --- Org B batch (create directly, not through create_batch which
    #     assumes ctx.project_id points to org-A's project) ---
    from tests_gauntlet._core import GAUNTLET_PREFIX
    import uuid
    b_batch_id = f'{GAUNTLET_PREFIX}mt1-b-{uuid.uuid4().hex[:8]}'
    AIAnalyzedBatch.objects.filter(
        batch_id__startswith=f'{GAUNTLET_PREFIX}mt1-b-',
    ).delete()
    org_b = Organisations.objects.get(id=org_b_id)
    proj_b = Project.objects.get(id=proj_b_id)
    b_batch = AIAnalyzedBatch.objects.create(
        batch_id=b_batch_id,
        project=proj_b,
        organisation=org_b,
        timestamp=timezone.now(),
        data={
            'logs': [
                _log('ERROR', f'tenant-B checkout: mysql conn refused. signature: {_BETA_SIG}',
                     'gauntlet-mt1-tenant-b', 4),
                _log('ERROR', f'tenant-B checkout: retry storm. signature: {_BETA_SIG}',
                     'gauntlet-mt1-tenant-b', 3),
                _log('ERROR', f'tenant-B checkout: circuit breaker OPEN. {_BETA_SIG}',
                     'gauntlet-mt1-tenant-b', 2),
            ],
            'metrics_summary': {'error_rate_pct': 62.0},
            'environment': 'production',
        },
        logs_analyzed=3,
    )
    analyze_batch.delay(b_batch_id)

    # --- Org A batch (real target of the assertion) ---
    a_batch_id = create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=[
            _log('ERROR', f'tenant-A checkout: redis conn refused. signature: {_ACME_SIG}',
                 ctx.org_name, 4),
            _log('ERROR', f'tenant-A checkout: connection pool exhausted. {_ACME_SIG}',
                 ctx.org_name, 3),
            _log('ERROR', f'tenant-A checkout: rejecting new sessions. {_ACME_SIG}',
                 ctx.org_name, 1),
        ],
        metrics_summary={'error_rate_pct': 88.0},
    )

    # --- Wait for org-B batch too, and raw-DB check both directions ---
    wait_for_analysis(b_batch_id, timeout=180)

    # Cross-tenant leak checks (raw DB): fail loudly if a leak happened.
    a_leak = Issue.objects.filter(organisation_id=ctx.org_id).filter(
        description__icontains=_BETA_SIG,
    ).exists() or Issue.objects.filter(organisation_id=ctx.org_id).filter(
        root_cause__icontains=_BETA_SIG,
    ).exists()
    b_leak = Issue.objects.filter(organisation_id=org_b_id).filter(
        description__icontains=_ACME_SIG,
    ).exists() or Issue.objects.filter(organisation_id=org_b_id).filter(
        root_cause__icontains=_ACME_SIG,
    ).exists()
    a_batch_leak = AIAnalyzedBatch.objects.get(batch_id=a_batch_id).analysis_text or ''
    b_batch_leak = AIAnalyzedBatch.objects.get(batch_id=b_batch_id).analysis_text or ''

    if _BETA_SIG in a_batch_leak or a_leak:
        raise AssertionError(
            f'CROSS-TENANT LEAK: org A batch/issues reference org B signature {_BETA_SIG!r}'
        )
    if _ACME_SIG in b_batch_leak or b_leak:
        raise AssertionError(
            f'CROSS-TENANT LEAK: org B batch/issues reference org A signature {_ACME_SIG!r}'
        )

    return a_batch_id


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains=['redis'],
    # Belt-and-braces: even if the raw-DB check above passed, the
    # returned batch's analysis_text must not carry the other tenant's
    # signature string.
    root_cause_does_not_contain=[_BETA_SIG, 'tenant-B', 'mysql'],
    timed_out_ok=False,
)
