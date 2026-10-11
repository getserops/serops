"""Gauntlet core — synth helpers + orchestration primitives.

Design decisions:

* **DB-first for batch creation.** Testing every log-provider ingest
  chain (11 adapters) is out of scope for a correctness gauntlet.
  ``create_batch()`` writes an ``AIAnalyzedBatch`` row directly with
  the same shape ``Data/tasks.py::create_log_batch_with_project_name``
  produces, then triggers ``analyze_batch.delay(batch_id)``. This
  isolates the AI + correlation + issue-persistence chain from the
  provider layer, which is exactly what a Tier-0 correctness gate
  needs.

* **HTTP-first for surfaces that HAVE an HTTP contract worth testing.**
  OTLP trace ingest (``/api/traces/v1/traces``), alert webhooks
  (``/api/webhooks/alerts/<source>/<org_id>/``) and CI/CD webhooks
  are tested via HTTP because the wire format IS the contract.

* **Idempotent + destructive-safe.** ``create_batch`` deletes any
  prior batch with the same ``batch_id`` before writing. Every
  gauntlet batch is prefixed ``gt-`` so an operator can wipe them
  with one query without touching real data.

* **Runs inside the backend container.** Import time uses ``django``,
  ``Data``, ``ai_model`` — must be invoked via
  ``docker exec serops-backend python -m tests_gauntlet.run_gauntlet``.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.utils import timezone


# Every gauntlet batch id starts with this so operators can wipe them
# safely with ``AIAnalyzedBatch.objects.filter(batch_id__startswith=GAUNTLET_PREFIX).delete()``.
GAUNTLET_PREFIX = 'gt-'


# ---------------------------------------------------------------------------
# Log-shaping helpers — shared across generators to cut duplication
# ---------------------------------------------------------------------------

def mk_t(seconds_ago: int) -> str:
    """ISO timestamp N seconds in the past."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def mk_log(level: str, message: str, seconds_ago: int = 0, *,
           service: str = 'checkout',
           project: str = 'gauntlet-checkout',
           organisation: str = 'Acme Cloud',
           environment: str = 'production') -> dict:
    """Flat log dict; ``_core.create_batch`` auto-wraps into ``_source``."""
    ts = mk_t(seconds_ago)
    return {
        'timestamp': ts, '@timestamp': ts,
        'level': level, 'log_level': level,
        'message': message,
        'service_name': service,
        'organisation_name': organisation,
        'project_name': project,
        'environment': environment,
    }


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class GauntletContext:
    """One-per-run config bundle.

    Read from env vars so the same code runs locally + on e2e without
    editing the code. Defaults target the e2e org provisioned on
    2026-09-20 (``Acme Cloud``, org #1).
    """
    org_id: int = int(os.environ.get('GAUNTLET_ORG_ID', '1'))
    org_name: str = os.environ.get('GAUNTLET_ORG_NAME', 'Acme Cloud')
    project_name: str = os.environ.get('GAUNTLET_PROJECT_NAME', 'gauntlet-checkout')
    project_service: str = os.environ.get('GAUNTLET_SERVICE', 'checkout')
    environment: str = os.environ.get('GAUNTLET_ENV', 'production')

    base_url: str = os.environ.get('GAUNTLET_BASE_URL', 'https://178-104-127-241.nip.io')
    user_email: str = os.environ.get('GAUNTLET_USER', 'gauntlet@serops.internal')
    user_password: str = os.environ.get('GAUNTLET_PWD', 'Gauntlet-Str0ngP4ss-2026')
    ingest_key: str = os.environ.get('GAUNTLET_INGEST_KEY', '')

    model: str = os.environ.get('GAUNTLET_MODEL', 'claude')

    # Per-run bookkeeping — populated by ensure_project()
    project_id: int | None = None
    service_id: int | None = None


# ---------------------------------------------------------------------------
# Fixture bootstrap
# ---------------------------------------------------------------------------

def set_default_provider(org_id: int, provider_name: str) -> str | None:
    """Set the org's default AI provider by name. Returns the previous
    default provider name (or ``None`` if none was set), so callers can
    restore it after the gauntlet run.
    """
    from org_settings.models import OrganisationAISettings, AIModelProvider
    prov = AIModelProvider.objects.filter(name=provider_name, is_active=True).first()
    if prov is None:
        raise RuntimeError(
            f'AI provider {provider_name!r} not active on this deployment.'
        )
    settings, _ = OrganisationAISettings.objects.get_or_create(organisation_id=org_id)
    prev = settings.default_provider.name if settings.default_provider else None
    settings.default_provider = prov
    settings.save(update_fields=['default_provider'])
    return prev


def restore_default_provider(org_id: int, previous_name: str | None):
    """Restore the org's default AI provider after a gauntlet run."""
    if previous_name is None:
        return
    from org_settings.models import OrganisationAISettings, AIModelProvider
    prov = AIModelProvider.objects.filter(name=previous_name).first()
    if prov is None:
        return
    settings = OrganisationAISettings.objects.filter(organisation_id=org_id).first()
    if settings is None:
        return
    settings.default_provider = prov
    settings.save(update_fields=['default_provider'])


def ensure_project(ctx: GauntletContext):
    """Idempotently ensure the gauntlet project + service exist on the target org.

    Runs once per gauntlet invocation so batch generators can reference
    ``ctx.project_id`` without each having to bootstrap.
    """
    from Organisations.models import Organisations
    from Projects.models import Project, ProjectEnvironment, ProjectService

    org = Organisations.objects.get(id=ctx.org_id)
    project, _ = Project.objects.get_or_create(
        organisation=org, name=ctx.project_name,
        defaults={'description': 'Gauntlet fixture project — safe to delete'},
    )
    service, _ = ProjectService.objects.get_or_create(
        project=project, name=ctx.project_service,
        defaults={'status': 'Active'},
    )
    ProjectEnvironment.objects.get_or_create(
        project=project, name=ctx.environment,
        defaults={'is_active': True},
    )
    ctx.project_id = project.id
    ctx.service_id = service.id
    return project


# ---------------------------------------------------------------------------
# Batch synthesis
# ---------------------------------------------------------------------------

def _batch_id(short: str) -> str:
    """Return a namespaced batch id.

    Format: ``gt-<short>-<8-hex>`` — deterministic prefix for filtering
    plus a random suffix so repeat runs don't collide (previous runs
    are deleted on collision anyway, but the suffix helps when the
    old run's celery task races the new one).
    """
    return f'{GAUNTLET_PREFIX}{short}-{uuid.uuid4().hex[:8]}'


def create_batch(
    ctx: GauntletContext,
    short_name: str,
    logs: list[dict] | None = None,
    metrics_summary: dict | None = None,
    code_changes: list[dict] | None = None,
    alerts: list[dict] | None = None,
    traces: list[dict] | None = None,
    extra_data: dict | None = None,
    run_sentinel: bool = True,
    batch_id_override: str | None = None,
) -> str:
    """Materialise one batch row and queue its AI analysis.

    Mirrors the shape ``Data.tasks.create_log_batch_with_project_name``
    produces so downstream ``analyze_batch`` sees a well-formed batch.
    Returns the generated batch_id — the caller uses it to await
    completion and assert expectations.

    ``run_sentinel`` (default True): also runs the Sentinel evaluator
    against the batch data and stamps ``sentinel_decision`` +
    ``sentinel_triggers`` before ``analyze_batch`` runs. This mirrors
    the full ingest chain (``Data.tasks.create_log_batch_with_project_name``
    calls Sentinel before queuing analysis), which is what generators
    testing Sentinel decisions need. When Sentinel active mode is on
    and the decision is 'quiet', ``ai_skipped=True`` is stamped and
    ``analyze_batch`` short-circuits — the same behaviour as prod.
    """
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project

    if ctx.project_id is None:
        ensure_project(ctx)

    org = Organisations.objects.get(id=ctx.org_id)
    project = Project.objects.get(id=ctx.project_id)

    if batch_id_override is not None:
        # Caller wants a stable id (e.g. UI-fixture seeding). Wipe any
        # prior row with this exact id so the run is idempotent.
        batch_id = batch_id_override
        AIAnalyzedBatch.objects.filter(batch_id=batch_id).delete()
    else:
        batch_id = _batch_id(short_name)
        # Wipe any dupes from earlier failed runs (short_name collisions
        # on the deterministic prefix). ``batch_id`` itself has a random
        # suffix so this only fires when the caller reuses the exact
        # short_name.
        AIAnalyzedBatch.objects.filter(
            batch_id__startswith=f'{GAUNTLET_PREFIX}{short_name}-',
            project=project,
        ).delete()

    # Sentinel + AI analyser both expect logs in the ES-nested shape
    # ``{'_id': ..., '_source': {level, message, ...}}``. Real ingest
    # produces this shape; the gauntlet helpers author flat dicts for
    # readability, so wrap them here. A dict that already has ``_source``
    # is passed through untouched (raw-control path).
    def _es_wrap(log_entry: dict, i: int) -> dict:
        if not isinstance(log_entry, dict):
            return {'_id': f'gt-{i}', '_source': {'message': str(log_entry), 'level': 'INFO'}}
        if '_source' in log_entry:
            return log_entry
        return {'_id': log_entry.get('_id', f'gt-{i}'), '_source': log_entry}

    wrapped_logs = [_es_wrap(l, i) for i, l in enumerate(logs or [])]

    data = {
        'logs': wrapped_logs,
        'metrics_summary': metrics_summary or {},
        'code_changes': code_changes or [],
        'alerts': alerts or [],
        'traces': traces or [],
        'environment': ctx.environment,
    }
    if extra_data:
        data.update(extra_data)

    batch = AIAnalyzedBatch.objects.create(
        batch_id=batch_id,
        project=project,
        organisation=org,
        timestamp=timezone.now(),
        data=data,
        logs_analyzed=len(wrapped_logs),
    )
    # Environment is a settable attribute on the batch — save_analysis
    # reads it via ``batch.environment or 'production'``.
    if hasattr(batch, 'environment') and 'environment' in [f.name for f in batch._meta.fields]:
        batch.environment = ctx.environment
        batch.save(update_fields=['environment'])

    # Sentinel gating (matches Data.tasks.create_log_batch_with_project_name)
    if run_sentinel:
        try:
            from Projects.models import ProjectEnvironment
            from Data.sentinel import evaluate_batch as sentinel_evaluate, _get_sentinel_config
            env_obj, _ = ProjectEnvironment.objects.get_or_create(
                project=project, name=ctx.environment,
                defaults={'is_active': True},
            )
            active_mode, thresholds = _get_sentinel_config(org)
            decision, triggers = sentinel_evaluate(
                project=project, environment=env_obj,
                batch_data=data, organisation=org,
                thresholds=thresholds,
            )
            batch.sentinel_decision = decision
            batch.sentinel_triggers = triggers
            update_fields = ['sentinel_decision', 'sentinel_triggers']
            if active_mode and decision == 'quiet' and hasattr(batch, 'ai_skipped'):
                batch.ai_skipped = True
                update_fields.append('ai_skipped')
            batch.save(update_fields=update_fields)
        except Exception:  # sentinel is best-effort in the gauntlet
            pass

    # Queue the analysis. Celery worker on e2e picks it up within ~1s.
    from ai_model.tasks import analyze_batch
    analyze_batch.delay(batch_id)
    return batch_id


# ---------------------------------------------------------------------------
# Completion polling
# ---------------------------------------------------------------------------

def wait_for_analysis(batch_id: str, timeout: float = 180.0, poll: float = 2.0) -> dict:
    """Block until ``analyzed_at`` is set (or Sentinel decides QUIET).

    Returns a summary dict {batch_id, analyzed_at, model_name,
    issue_count, analysis_text, sentinel_decision, timed_out}.
    Timeout is a hard cap: some AI providers can be slow.
    """
    from Data.models import AIAnalyzedBatch

    started = time.monotonic()
    while True:
        try:
            batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
        except AIAnalyzedBatch.DoesNotExist:
            batch = None

        elapsed = time.monotonic() - started
        # Two completion signals:
        # 1. ``analyzed_at`` set → normal AI-analysis path completed.
        # 2. ``ai_skipped=True`` → Sentinel gated the batch out; there
        #    will never be an ``analyzed_at`` and we shouldn't wait.
        if batch:
            ai_skipped = getattr(batch, 'ai_skipped', False)
            if batch.analyzed_at or ai_skipped:
                return _summarise(batch, elapsed)
        if elapsed > timeout:
            return _summarise(batch, elapsed, timed_out=True)
        time.sleep(poll)


def _summarise(batch, elapsed_s, timed_out=False):
    if batch is None:
        return {
            'batch_id': None, 'timed_out': timed_out,
            'elapsed_s': elapsed_s, 'exists': False,
        }
    return {
        'batch_id': batch.batch_id,
        'exists': True,
        'analyzed_at': batch.analyzed_at.isoformat() if batch.analyzed_at else None,
        'model_name': batch.model_name,
        'issue_count': batch.issue_count,
        'analysis_text': batch.analysis_text,
        'sentinel_decision': getattr(batch, 'sentinel_decision', None),
        'sentinel_triggers': getattr(batch, 'sentinel_triggers', None),
        'ai_skipped': getattr(batch, 'ai_skipped', False),
        'elapsed_s': elapsed_s,
        'timed_out': timed_out,
    }


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------

@dataclass
class Expectation:
    """What a Tier-0/1/2 batch should look like after analysis.

    Fields are all optional — the runner asserts only what's set. Keep
    assertions tight: "issues >= 1" is more robust than "issues == 3"
    across Gemini vs Claude output variability.
    """
    min_issues: int | None = None
    max_issues: int | None = None
    root_cause_contains: list[str] = field(default_factory=list)
    root_cause_contains_any: list[str] = field(default_factory=list)
    root_cause_does_not_contain: list[str] = field(default_factory=list)
    analysis_text_starts_with: str | None = None
    sentinel_decision: str | None = None  # 'first' | 'quiet' | 'alert'
    sentinel_triggers_contains: list[str] = field(default_factory=list)
    ai_skipped_expected: bool | None = None  # True → AI must have been skipped
    model_name_contains: str | None = None
    timed_out_ok: bool = False


def check_expectation(summary: dict, exp: Expectation) -> tuple[bool, list[str]]:
    """Return (passed, failures). Empty failures = pass."""
    fails = []
    if summary.get('timed_out') and not exp.timed_out_ok:
        fails.append(f'analysis timed out after {summary["elapsed_s"]:.1f}s')
        return False, fails

    ic = summary.get('issue_count') or 0
    if exp.min_issues is not None and ic < exp.min_issues:
        fails.append(f'issue_count {ic} < min {exp.min_issues}')
    if exp.max_issues is not None and ic > exp.max_issues:
        fails.append(f'issue_count {ic} > max {exp.max_issues}')

    at = (summary.get('analysis_text') or '').lower()
    for needle in exp.root_cause_contains:
        if needle.lower() not in at:
            fails.append(f'analysis_text missing expected substring: {needle!r}')
    if exp.root_cause_contains_any:
        if not any(n.lower() in at for n in exp.root_cause_contains_any):
            fails.append(
                'analysis_text missing ANY of expected substrings: '
                f'{exp.root_cause_contains_any!r}'
            )
    for needle in exp.root_cause_does_not_contain:
        if needle.lower() in at:
            fails.append(f'analysis_text contains forbidden substring: {needle!r}')
    if exp.analysis_text_starts_with and not at.startswith(exp.analysis_text_starts_with):
        fails.append(f'analysis_text does not start with {exp.analysis_text_starts_with!r}')

    sd = (summary.get('sentinel_decision') or '').lower()
    if exp.sentinel_decision and sd != exp.sentinel_decision.lower():
        fails.append(f'sentinel_decision {sd!r} != expected {exp.sentinel_decision!r}')

    triggers = summary.get('sentinel_triggers') or []
    for t in exp.sentinel_triggers_contains:
        if t not in triggers:
            fails.append(f'sentinel_triggers {triggers!r} missing {t!r}')

    if exp.ai_skipped_expected is not None:
        actual_skipped = bool(summary.get('ai_skipped'))
        if actual_skipped != exp.ai_skipped_expected:
            fails.append(f'ai_skipped={actual_skipped} != expected {exp.ai_skipped_expected}')

    mn = (summary.get('model_name') or '').lower()
    if exp.model_name_contains and exp.model_name_contains.lower() not in mn:
        fails.append(f'model_name {mn!r} missing {exp.model_name_contains!r}')

    return len(fails) == 0, fails


# ---------------------------------------------------------------------------
# HTTP surfaces (alert webhooks, OTLP)
# ---------------------------------------------------------------------------

def push_alert(ctx: GauntletContext, source: str, alert: dict, verify_tls: bool = False):
    """POST an alert to /api/webhooks/alerts/<source>/<org_id>/.

    ``source`` is 'alertmanager', 'grafana', 'pagerduty' etc — the
    dispatcher normalises the shape. Returns (status_code, response_json).
    """
    import requests
    url = f'{ctx.base_url}/api/webhooks/alerts/{source}/{ctx.org_id}/'
    r = requests.post(url, json=alert, timeout=15, verify=verify_tls)
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {'raw': r.text[:500]}


def push_otlp_trace(ctx: GauntletContext, otlp_payload: dict, verify_tls: bool = False):
    """POST an OTLP JSON payload to /api/traces/v1/traces with Bearer <ingest_key>."""
    import requests
    if not ctx.ingest_key:
        raise RuntimeError('GAUNTLET_INGEST_KEY not set — cannot push OTLP traces')
    url = f'{ctx.base_url}/api/traces/v1/traces'
    r = requests.post(
        url, json=otlp_payload, timeout=15, verify=verify_tls,
        headers={'Authorization': f'Bearer {ctx.ingest_key}'},
    )
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {'raw': r.text[:500]}
