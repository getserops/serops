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

from . import held_out, held_out_v2, held_out_v3, tuned
from .scoring import score, sequence_checks, severity_between

SETS = {'tuned': tuned.SCENARIOS, 'held_out': held_out.SCENARIOS, 'held_out_v2': held_out_v2.SCENARIOS,
        'held_out_v3': held_out_v3.SCENARIOS,
        # held-out scenarios moved to the tuned set (2026-11-16; v3 w19, w36-w40; v2 v29); opt-in
        'tuned_v3': held_out_v3.MOVED_TO_TUNED + held_out_v2.MOVED_TO_TUNED}


def select(sets=('held_out', 'tuned'), only=()):
    builds = [b for name in sets for b in SETS[name]]
    if only:
        builds = [b for b in builds if any(b.__name__.startswith(o) for o in only)]
    return builds


def _issue_dict(issue):
    return {'id': issue.pk, 'severity': issue.severity, 'confidence': issue.confidence, 'component': issue.component,
            'affected_services': issue.affected_services or [], 'description': issue.description,
            'root_cause': issue.root_cause, 'recommendation': issue.recommendation,
            'linked_commits': issue.linked_commits, 'reasoning': issue.reasoning}


# Data sources an ablation run can take out of every scenario.
DROPPABLE = {'traces': ('traces', 'traces_summary'), 'metrics': ('metrics_summary', 'metrics'),
             'code': ('code_changes',)}


def _setup_org(provider, api_key, budget_usd, model=None):
    from Organisations.models import Organisations
    from org_settings.models import AIModelProvider, OrganisationAISettings, OrganisationAPIKey

    org = Organisations.objects.create(name=f'RCA Benchmark {uuid.uuid4().hex[:8]}')
    chosen = AIModelProvider.objects.get(name=provider)
    if model:  # the benchmark database is throwaway: the row is set per run
        chosen.default_model = model
        chosen.save(update_fields=['default_model'])
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
# The provider account refuses every call until someone acts: stop the run
# instead of retrying each scenario against it.
ACCOUNT_REFUSED = ('SPEND_LIMIT', 'OUT_OF_CREDIT', 'AUTH_ERROR')


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


def _analyse(org, project, scenario_id, data, pause, retries):
    """One batch through the real analysis: (issues, error, seconds, cost,
    tokens in, tokens out, batch, stop reason or None)."""
    from Data.models import AIAnalyzedBatch, Issue
    from ai_model.tasks import analyze_batch

    batch_id = f"rca-bench-{scenario_id}-{uuid.uuid4().hex[:8]}"
    batch = AIAnalyzedBatch.objects.create(batch_id=batch_id, project=project, organisation=org,
                                           environment='production', data=data)
    error, refused = None, None
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
        if any(code in str(batch.model_name or '') for code in ACCOUNT_REFUSED):
            refused = f'provider refused the account: {batch.model_name}'
            break
        if attempt < retries:
            time.sleep(max(pause, 30))
    seconds = round(time.monotonic() - started, 1)
    if str(batch.model_name or '').startswith(NOT_ANALYSED):
        error = error or str(batch.model_name)
    issues = [_issue_dict(i) for i in Issue.objects.filter(occurrences__batch=batch).distinct().order_by('id')]
    cost, tin, tout = _spent(org, batch)
    return issues, error, seconds, cost, tin, tout, batch, refused


def run(builds, provider, api_key, repeat=1, budget_usd=1.0, pause=0, retries=2, keep=False, on_result=None,
        model=None, drop=()):
    """Run each scenario ``repeat`` times. Returns (results, stopped): stopped
    says why the run ended early (budget reached), or is None.

    ``model`` sets the provider's model for the run. ``drop`` names data
    sources (see DROPPABLE) taken out of every scenario before analysis;
    a scenario that has none of them is skipped, since the run would only
    repeat the full-data one. The answer key is never changed."""
    from Projects.models import Project

    org, chosen = _setup_org(provider, api_key, budget_usd, model)
    results, stopped = [], None
    try:
        for attempt_round in range(repeat):
            for build in builds:
                spent, _, _ = _spent(org)
                if spent >= budget_usd:
                    stopped = f'budget reached: spent ${spent:.4f} of ${budget_usd:.2f}'
                    break
                sc = build()
                if drop:
                    datas = [w['data'] for w in sc['batches']] if 'batches' in sc else [sc['data']]
                    if not any(k in data for data in datas for d in drop for k in DROPPABLE[d]):
                        continue
                project = Project.objects.create(name=f"{sc['id']}-{attempt_round + 1}", organisation=org)
                windows = sc.get('batches') or [{'data': sc['data'], 'answer': sc['answer']}]
                seen = []
                for n, window in enumerate(windows, 1):
                    data = window['data']
                    if drop:
                        data = {k: v for k, v in data.items()
                                if k not in {x for d in drop for x in DROPPABLE[d]}}
                    issues, error, seconds, cost, tin, tout, batch, refused = _analyse(
                        org, project, f"{sc['id']}-{n}" if 'batches' in sc else sc['id'], data, pause, retries)
                    stopped = stopped or refused
                    seen.append(issues)
                    sc_score = score(window['answer'], issues) if not error else None
                    if sc_score and window.get('severity'):
                        sc_score['checks']['severity'] = severity_between(issues, *window['severity'])
                    if sc_score and 'batches' in sc and n == len(windows):
                        sc_score['checks'].update(sequence_checks(sc['sequence'], seen))
                    if sc_score:
                        sc_score['verdict'] = all(sc_score['checks'].values())
                        if sc_score['kind'] == 'healthy':
                            sc_score['root_cause'] = sc_score['lenient'] = sc_score['verdict']
                    multi = 'batches' in sc
                    result = {
                        'id': f"{sc['id']}#{n}" if multi else sc['id'], 'set': sc['set'], 'category': sc['category'],
                        'name': f"{sc['name']} — window {n}/{len(windows)}: {window.get('label', '')}" if multi
                        else sc['name'],
                        'round': attempt_round + 1, 'provider': chosen.name, 'dropped': list(drop),
                        'model': chosen.default_model or _model(org, batch) or batch.model_name, 'ai_called': tin > 0,
                        'error': error, 'seconds': seconds, 'cost_usd': round(cost, 6),
                        'tokens_input': tin, 'tokens_output': tout, 'issues': issues,
                        'answer': window['answer'], 'score': sc_score,
                    }
                    if multi:
                        result['sequence'] = sc['id']
                    results.append(result)
                    if on_result:
                        on_result(result)
                    if stopped:
                        break
                    if pause and n < len(windows):
                        time.sleep(pause)
                if stopped:
                    break
                if pause:
                    time.sleep(pause)
            if stopped:
                break
    finally:
        if not keep:
            org.delete()
    return results, stopped
