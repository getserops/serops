"""
Run scenarios through the real analysis task and collect what it created.

Everything happens in a throwaway organisation, deleted at the end: one
project per scenario run, so issue memory, deduplication and recurrence
from one incident can't leak into the next. The organisation uses only the
key it is given, with no fallback provider, and SerOps' own monthly budget
cap is set to the run's budget as a second stop.
"""
import time
import uuid
from decimal import Decimal

from . import held_out, tuned
from .scoring import score

SETS = {'tuned': tuned.SCENARIOS, 'held_out': held_out.SCENARIOS}


def select(sets=('held_out', 'tuned'), only=()):
    builds = [b for name in sets for b in SETS[name]]
    if only:
        builds = [b for b in builds if any(b.__name__.startswith(o) for o in only)]
    return builds


def _issue_dict(issue):
    return {'severity': issue.severity, 'confidence': issue.confidence, 'component': issue.component,
            'affected_services': issue.affected_services or [], 'description': issue.description,
            'root_cause': issue.root_cause, 'recommendation': issue.recommendation,
            'linked_commits': issue.linked_commits, 'reasoning': issue.reasoning}


def _setup_org(provider, api_key, budget_usd):
    from Organisations.models import Organisations
    from org_settings.models import AIModelProvider, OrganisationAISettings, OrganisationAPIKey

    org = Organisations.objects.create(name=f'RCA Benchmark {uuid.uuid4().hex[:8]}')
    chosen = AIModelProvider.objects.get(name=provider)
    OrganisationAPIKey.objects.create(organisation=org, provider=chosen, api_key=api_key, is_active=True)
    settings, _ = OrganisationAISettings.objects.get_or_create(organisation=org)
    settings.default_provider = chosen
    settings.fallback_provider = None
    settings.use_custom_keys = True
    settings.monthly_budget_usd = Decimal(str(budget_usd))
    settings.save()
    return org, chosen


# Batch outcomes that mean no analysis happened: never scored as "quiet".
NOT_ANALYSED = ('FAILED', 'unconfigured', 'budget_exceeded', 'SKIPPED')


def _model(org, batch):
    from ai_model.models import AITokenUsage
    row = AITokenUsage.objects.filter(organisation=org, batch=batch).order_by('-id').first()
    return row.model_name if row else None


def _spent(org, batch=None):
    from django.db.models import Sum
    from ai_model.models import AITokenUsage
    rows = AITokenUsage.objects.filter(organisation=org)
    if batch is not None:
        rows = rows.filter(batch=batch)
    agg = rows.aggregate(cost=Sum('cost_usd'), tin=Sum('tokens_input'), tout=Sum('tokens_output'))
    return float(agg['cost'] or 0), int(agg['tin'] or 0), int(agg['tout'] or 0)


def run(builds, provider, api_key, repeat=1, budget_usd=1.0, pause=0, retries=2, keep=False, on_result=None):
    """Run each scenario ``repeat`` times. Returns (results, stopped): stopped
    says why the run ended early (budget reached), or is None."""
    from Data.models import AIAnalyzedBatch, Issue
    from Projects.models import Project
    from ai_model.tasks import analyze_batch

    org, chosen = _setup_org(provider, api_key, budget_usd)
    results, stopped = [], None
    try:
        for attempt_round in range(repeat):
            for build in builds:
                spent, _, _ = _spent(org)
                if spent >= budget_usd:
                    stopped = f'budget reached: spent ${spent:.4f} of ${budget_usd:.2f}'
                    break
                sc = build()
                project = Project.objects.create(name=f"{sc['id']}-{attempt_round + 1}", organisation=org)
                batch_id = f"rca-bench-{sc['id']}-{uuid.uuid4().hex[:8]}"
                batch = AIAnalyzedBatch.objects.create(batch_id=batch_id, project=project, organisation=org,
                                                       environment='production', data=sc['data'])
                error = None
                started = time.monotonic()
                for attempt in range(retries + 1):
                    try:
                        analyze_batch(batch_id)
                        error = None
                    except Exception as exc:  # reported, never hidden
                        error = f'{type(exc).__name__}: {exc}'[:300]
                    batch.refresh_from_db()
                    if not str(batch.model_name or '').startswith(NOT_ANALYSED) and error is None:
                        break
                    if attempt < retries:
                        time.sleep(max(pause, 30))
                seconds = round(time.monotonic() - started, 1)
                if str(batch.model_name or '').startswith(NOT_ANALYSED):
                    error = error or str(batch.model_name)
                issues = [_issue_dict(i) for i in
                          Issue.objects.filter(occurrences__batch=batch).distinct().order_by('id')]
                cost, tin, tout = _spent(org, batch)
                result = {
                    'id': sc['id'], 'set': sc['set'], 'category': sc['category'], 'name': sc['name'],
                    'round': attempt_round + 1, 'provider': chosen.name,
                    'model': chosen.default_model or _model(org, batch) or batch.model_name, 'ai_called': tin > 0,
                    'error': error, 'seconds': seconds, 'cost_usd': round(cost, 6),
                    'tokens_input': tin, 'tokens_output': tout, 'issues': issues,
                    'answer': sc['answer'], 'score': score(sc['answer'], issues) if not error else None,
                }
                results.append(result)
                if on_result:
                    on_result(result)
                if pause:
                    time.sleep(pause)
            if stopped:
                break
    finally:
        if not keep:
            org.delete()
    return results, stopped
