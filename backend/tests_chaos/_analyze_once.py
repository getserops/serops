"""Runs INSIDE the SerOps backend pod. Creates one batch from live cluster
signals, analyses it with the configured provider, and prints a single JSON
line for the host-side harness to score.

Kept separate from the harness so the only thing crossing the kubectl exec
boundary is JSON — no shell quoting of scenario data, and the harness stays
readable.
"""
import json
import os
import sys

from Data.models import AIAnalyzedBatch, Issue
from Data.tasks import create_log_batch_with_project_name
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment

ORG = 'gauntlet-org'
PROJECT = 'gauntlet-project'

out = {'ok': False}
try:
    org = Organisations.objects.get(name=ORG)
    project = Project.objects.get(organisation=org, name=PROJECT)
    env = ProjectEnvironment.objects.get(project=project, name='production')

    # An EXPLICIT window covering only this scenario's soak period.
    #
    # Left to itself the task resumes from the previous batch's end, so the
    # window stretched back hours and swept in logs from pods that had since
    # been deleted — the first trial "passed" by diagnosing a workload that
    # no longer existed. The alert-triggered path already supports a pinned
    # window for exactly this reason.
    window_start = os.environ.get('CHAOS_WINDOW_START') or None
    window_end = os.environ.get('CHAOS_WINDOW_END') or None

    # Clear per-environment Sentinel state so each scenario is judged on its
    # own signals. known_log_patterns accumulates across batches, so a
    # pattern seen in scenario N is no longer "new" in scenario N+1 and
    # new_error_pattern would stop firing partway through the run.
    if os.environ.get('CHAOS_RESET_STATE') == '1':
        from Data.models import ProjectEnvironmentState
        ProjectEnvironmentState.objects.filter(project=project).delete()

    task_result = create_log_batch_with_project_name(
        project_name=PROJECT, project=project.id,
        environment=env.id, interval_minutes=15,
        window_start_iso=window_start, window_end_iso=window_end,
    )
    out['task_result'] = str(task_result)[:200]
    out['window'] = {'start': window_start, 'end': window_end}

    # Only accept a batch created by THIS call.
    #
    # create_log_batch_with_project_name declines when it finds nothing new
    # ("No new logs or metrics found..."), and simply taking the newest batch
    # then scores the PREVIOUS scenario's analysis as if it were this one.
    # That is how the first trial run "passed" while describing pods that had
    # already been deleted.
    import re
    match = re.search(r'created batch (\S+)', str(task_result))
    batch = (AIAnalyzedBatch.objects.filter(
        organisation=org, batch_id=match.group(1)).first()
        if match else None)
    if batch is None:
        out['error'] = (f'no batch created for this window; '
                        f'task said: {str(task_result)[:140]}')
        print(json.dumps(out))
        sys.exit(0)

    data = batch.data if isinstance(batch.data, dict) else {}
    out['batch_id'] = batch.batch_id
    out['logs'] = len(data.get('logs') or [])
    out['sentinel_decision'] = batch.sentinel_decision
    out['sentinel_triggers'] = batch.sentinel_triggers or []
    summary = data.get('metrics_summary') or {}
    out['metrics'] = {
        'cpu_points': (summary.get('data_points') or {}).get('cpu'),
        'mem_points': (summary.get('data_points') or {}).get('memory'),
        'cpu_avg': ((summary.get('cpu') or {}).get('usage_percent') or {}).get('avg'),
        'mem_avg': ((summary.get('memory') or {}).get('usage_percent') or {}).get('avg'),
        'anomalies': len(((summary.get('memory') or {}).get('anomalies') or []))
                     + len(((summary.get('cpu') or {}).get('anomalies') or [])),
    }
    traces = data.get('traces') or {}
    out['traces'] = {
        'present': bool(traces),
        'span_count': traces.get('span_count') if isinstance(traces, dict) else None,
    }

    from ai_model.tasks import analyze_batch
    try:
        analyze_batch(batch.batch_id)
    except Exception as exc:                       # noqa: BLE001
        out['analyze_error'] = f'{type(exc).__name__}: {str(exc)[:200]}'

    batch.refresh_from_db()
    out['model_name'] = batch.model_name
    out['narrative'] = (batch.analysis_text or '')[:1200]

    # Real spend, from the usage rows SerOps already writes per call — so the
    # budget cap is enforced on measured cost, not a guess.
    from decimal import Decimal
    from django.db.models import Sum
    from ai_model.models import AITokenUsage
    agg = AITokenUsage.objects.filter(organisation=org).aggregate(
        cost=Sum('cost_usd'), tin=Sum('tokens_input'), tout=Sum('tokens_output'))
    out['spend'] = {
        'cumulative_usd': float(agg['cost'] or Decimal('0')),
        'tokens_in': int(agg['tin'] or 0),
        'tokens_out': int(agg['tout'] or 0),
    }
    this_call = AITokenUsage.objects.filter(batch=batch).aggregate(
        cost=Sum('cost_usd'))['cost']
    out['spend']['this_scenario_usd'] = float(this_call or Decimal('0'))

    # Score what THIS analysis said, not what the Issue table happens to point
    # at. Recurrence calls `existing.move_to_batch(batch)`, so an Issue's batch
    # FK tracks its MOST RECENT sighting — `Issue.objects.filter(batch=batch)`
    # therefore means "issues last seen in this batch", which includes issues
    # opened hours earlier by a different scenario.
    #
    # That mismeasurement failed the healthy-window scenario: the model
    # correctly returned zero issues, and the harness scored issue_count=1 from
    # a stale row (created 06:19, occurrence 9) whose FK had been moved onto the
    # healthy batch. Reading the analysis payload is the only way to score the
    # model's own answer.
    # The parsed analysis lives in analysis_history, NOT in
    # batch.data['analysis_result'] — save_analysis's docstring claims the
    # latter but its update_fields never includes `data`, so that key is always
    # absent. Reading it returned an empty dict for every batch, which scored a
    # correct 4-issue cascade as "0 issues" until this was caught.
    _history = batch.analysis_history or []
    _primary = [h for h in _history if h.get('is_primary')] or _history[-1:]
    analysis = (_primary[0].get('analysis_result') if _primary else {}) or {}
    if not isinstance(analysis, dict):
        analysis = {}
    issues = []
    for entry in (analysis.get('correlated_issues') or []):
        if not isinstance(entry, dict):
            continue
        issues.append({
            'severity': entry.get('severity'),
            'issue_type': entry.get('issue_type'),
            'component': entry.get('component'),
            'description': (entry.get('description') or '')[:400],
            'root_cause': (entry.get('root_cause') or '')[:400],
        })
    out['issues'] = issues
    # Kept for visibility: a large gap between the two is worth knowing about.
    out['issues_linked_to_batch'] = Issue.objects.filter(batch=batch).count()
    out['ok'] = True
except Exception as exc:                            # noqa: BLE001
    out['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'

print(json.dumps(out))
