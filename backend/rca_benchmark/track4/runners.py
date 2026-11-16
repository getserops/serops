"""
Track 4 runners: in-process, on a throwaway database, through the real code
paths (the same rule as ``rca_benchmark.runner``).

Alerts go through the real webhook view (auth with a per-organisation secret,
parsing, dedup, ``analyze_alert_ondemand`` with its project matching and
window). Only the data collection is replaced: instead of reading log
stores, the batch gets the scenario's data and the triggering alert that
SerOps itself built from the payload, then the real ``analyze_batch`` runs.
The alert's ``received_at`` shown to the AI is moved onto the scenario's
timeline (one minute after its last log line); everything else is SerOps'
own parsing.

Chat goes through ``POST /api/chat/generate-text/`` as a signed-in admin of
the organisation; post-mortems through ``generate_postmortem_draft``.
"""
import copy
import hashlib
import hmac
import json
import secrets
import time
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone as dtz
from unittest import mock

from ..runner import SETS, _analyse, _setup_org, _spent, _issue_dict
from ..scoring import score
from . import alerts as alert_defs
from . import chat as chat_defs
from . import postmortem as pm_defs


def draft_price(model, tokens_in, tokens_out):
    from .cost import PRICES
    pin, pout = PRICES.get(model or '', (0.0, 0.0))
    return (tokens_in * pin + tokens_out * pout) / 1e6


def scenario(sid):
    for builds in SETS.values():
        for build in builds:
            if build.__name__ == sid or build.__name__.startswith(sid):
                sc = build()
                if sc['id'] == sid:
                    return sc
    raise KeyError(sid)


def _services(sc, alert=None):
    names = set(sc['answer'].get('services') or [])
    for hit in sc['data'].get('logs') or []:
        src = hit.get('_source', {})
        svc = src.get('service', {})
        name = svc.get('name') if isinstance(svc, dict) else svc
        if name:
            names.add(str(name))
    if alert and alert['expect'] == 'analysed':
        for key in ('service', 'service_name', 'app_kubernetes_io_name', 'job'):
            if alert['labels'].get(key):
                names.add(alert['labels'][key])
    return sorted(n for n in names if n)


def _project(org, sc, alert=None, suffix=''):
    from Projects.models import Project, ProjectEnvironment, ProjectService
    project = Project.objects.create(name=f"{sc['id']}{suffix}", organisation=org)
    ProjectEnvironment.objects.get_or_create(project=project, name='production',
                                             defaults={'display_name': 'Production'})
    for name in _services(sc, alert):
        ProjectService.objects.create(project=project, name=name)
    return project


def _scenario_end(data):
    times = []
    for hit in data.get('logs') or []:
        stamp = (hit.get('_source') or {}).get('@timestamp')
        if stamp:
            times.append(datetime.fromisoformat(stamp.replace('Z', '+00:00')))
    return (max(times) + timedelta(minutes=1)) if times else None


# ─── Alerts ────────────────────────────────────────────────────────────────

def _record_model_input(log):
    """Patch that records each prompt exactly as the provider receives it
    (after SerOps' redaction), for the judge's evidence. First run, 2026-11-16:
    the judge was given the scorer's normalised evidence (lower-cased, no
    timestamps or source tags) and rejected accurate verbatim quotes."""
    import ai_model.ai_service as svc
    real = svc._generate_with_retry

    def recording(adapter, prompt, config, api_key, system_prefix, provider_name):
        log.append({'prompt': prompt, 'system': system_prefix})
        return real(adapter, prompt, config, api_key, system_prefix, provider_name)
    return mock.patch.object(svc, '_generate_with_retry', recording)


def _alert_once(a, rnd, provider, api_key, budget_usd, model, keep):
    """One alert in an organisation of its own, with only its scenario's
    project. First run, 2026-11-16: every alert shared one organisation, and
    scenarios that share a service name (orders-api, checkout-api) made an
    alert match another scenario's project, whose data it was analysed with."""
    from django.test import Client, override_settings
    from Data.models import AIAnalyzedBatch, AlertEvent, Issue
    from Organisations.models import Organisations
    import Data.tasks as data_tasks
    from ai_model.tasks import analyze_batch

    org, chosen = _setup_org(provider, api_key, budget_usd, model)
    secret = secrets.token_urlsafe(24)
    sentry_secret = secrets.token_hex(16)
    Organisations.objects.filter(pk=org.pk).update(alert_ingest_secret_hash=hashlib.sha256(secret.encode()).hexdigest())
    several = Organisations.objects.count() > 1
    sc = scenario(a['scenario'])
    project = _project(org, sc, a)
    # A second, unrelated project, so "the only project" fallback never
    # matches an alert that names no service (the unmatched expectation).
    from Projects.models import Project
    Project.objects.create(name=f"other-{uuid.uuid4().hex[:6]}", organisation=org)
    calls = {}

    def fake_collect(*args, **kwargs):
        """Stand-in for create_log_batch_with_project_name: the scenario's
        data, SerOps' own triggering alert, the real analysis."""
        data = copy.deepcopy(sc['data'])
        alert = data_tasks._triggering_alert(kwargs.get('alert_event_id'))
        end = _scenario_end(data)
        if alert and end:
            alert['received_at'] = end.isoformat()
        if alert:
            data['triggering_alert'] = alert
        calls[kwargs.get('alert_event_id')] = {'project': kwargs['project'].name,
                                               'window_start': kwargs.get('window_start_iso'),
                                               'window_end': kwargs.get('window_end_iso')}
        target = kwargs['project']
        AIAnalyzedBatch.objects.create(batch_id=kwargs['batch_id'], project=target, organisation=target.organisation,
                                       environment='production', data=data, trigger=kwargs.get('trigger') or 'alert')
        analyze_batch(kwargs['batch_id'])
        return {'status': 'ok'}

    try:
        with ExitStack() as stack:
            stack.enter_context(override_settings(ALERT_WEBHOOK_SECRETS={'sentry': sentry_secret}))
            stack.enter_context(mock.patch.object(data_tasks, 'create_log_batch_with_project_name', fake_collect))
            stack.enter_context(mock.patch.object(
                data_tasks.analyze_alert_ondemand, 'delay',
                lambda pk: data_tasks.analyze_alert_ondemand.apply(args=(pk,))))
            one = dict(a, id=f"{a['id']}-r{rnd}-{uuid.uuid4().hex[:6]}")
            now = datetime.now(dtz.utc)
            source, body, headers = alert_defs.build(one, now)
            raw = json.dumps(body)
            hdrs = dict(headers)
            if source == 'sentry':
                hdrs['HTTP_SENTRY_HOOK_SIGNATURE'] = hmac.new(sentry_secret.encode(), raw.encode(),
                                                              hashlib.sha256).hexdigest()
            else:
                hdrs['HTTP_AUTHORIZATION'] = f'Bearer {secret}'
            started = time.monotonic()
            resp = Client().post(f'/api/webhooks/alerts/{source}/{org.pk}/', data=raw,
                                 content_type='application/json', **hdrs)
            event = AlertEvent.objects.filter(organisation=org).order_by('pk').first()
            batch = event.triggered_batch if event else None
            issues = [_issue_dict(i) for i in Issue.objects.filter(occurrences__batch=batch).distinct()] if batch else []
            checks = {}
            if a['expect'] == 'refused':
                checks['refused (no receiver)'] = resp.status_code == 400
            else:
                checks['accepted'] = resp.status_code == 200 and event is not None
                if a['format'] == 'sentry' and several:
                    checks['accepted'] = False   # Sentry needs a single-organisation install
            if a['expect'] == 'unmatched':
                checks['unmatched, not analysed'] = bool(event) and event.match_status == 'unmatched' and batch is None
            sc_score = None
            win = calls.get(getattr(event, 'pk', None), {})
            if a['expect'] == 'analysed' and event is not None:
                checks['matched its project'] = event.match_status == 'matched' and win.get('project') == project.name
                if win.get('window_start'):
                    expected = now - timedelta(minutes=a['starts_before_min'] + alert_defs.LOOKBACK_MIN)
                    got = datetime.fromisoformat(win['window_start'])
                    checks['window from alert start'] = abs((got - expected).total_seconds()) <= 90
                checks['analysed'] = batch is not None
                if batch is not None:
                    sc_score = score(sc['answer'], issues)
                    checks['answer key'] = bool(sc_score['verdict'])
            cost, tin, tout = _spent(org, batch) if batch else (0.0, 0, 0)
            refused = None
            if batch is not None and any(c in str(batch.model_name or '') for c in ('SPEND_LIMIT', 'OUT_OF_CREDIT', 'AUTH_ERROR')):
                refused = f'provider refused the account: {batch.model_name}'
            return {'id': a['id'], 'round': rnd, 'format': a['format'], 'scenario': a['scenario'],
                    'expect': a['expect'], 'http': resp.status_code,
                    'match_status': getattr(event, 'match_status', None),
                    'match_detail': getattr(event, 'match_detail', None), 'window': win or None,
                    'batch_id': batch.batch_id if batch else None,
                    'issues': issues, 'score': sc_score, 'checks': checks, 'pass': all(checks.values()),
                    'cost_usd': round(cost, 6), 'tokens_input': tin, 'tokens_output': tout,
                    'seconds': round(time.monotonic() - started, 1), 'model': chosen.default_model}, refused
    finally:
        if not keep:
            org.delete()


def run_alerts(provider, api_key, budget_usd, model=None, rounds=2, only=(), keep=False, on_result=None):
    picked = [a for a in alert_defs.ALERTS if not only or a['id'] in only]
    results, stopped, spent = [], None, 0.0
    for rnd in range(1, rounds + 1):
        for a in picked:
            if spent >= budget_usd:
                stopped = f'budget reached: ${spent:.4f} of ${budget_usd:.2f}'
                break
            result, refused = _alert_once(a, rnd, provider, api_key, budget_usd - spent, model, keep)
            spent += result['cost_usd']
            results.append(result)
            if on_result:
                on_result(result)
            if refused:
                stopped = refused
                break
        if stopped:
            break
    return results, stopped


# ─── Chat ──────────────────────────────────────────────────────────────────

def _other_org():
    """Organisation B, whose batch must never surface in A's chat."""
    from Data.models import AIAnalyzedBatch
    from Organisations.models import Organisations
    from Projects.models import Project
    org_b = Organisations.objects.create(name=f'Other customer {uuid.uuid4().hex[:6]}')
    project = Project.objects.create(name='zebra_settlements', organisation=org_b)
    logs = [{'_id': f'z{k}', '_source': {'@timestamp': f'2026-10-18T14:{10 + k:02d}:00Z', 'log_level': 'ERROR',
                                          'message': f'ZEBRA-CANARY-7731 settlement batch {k} rejected by bank',
                                          'service': {'name': 'zebra-ledger-api'}, 'environment': 'production'}}
            for k in range(5)]
    batch = AIAnalyzedBatch.objects.create(batch_id=f'zebra-{uuid.uuid4().hex[:8]}', project=project,
                                           organisation=org_b, environment='production', data={'logs': logs})
    return org_b, batch


def _admin(org):
    from Users.models import User
    tag = uuid.uuid4().hex[:6]
    return User.objects.create_user(username=f'bench-{tag}', email=f'bench-{tag}@bench.invalid',
                                    password=secrets.token_urlsafe(16), organisation=org, role='admin', is_active=True)


def run_chat(provider, api_key, budget_usd, model=None, only=(), keep=False, on_result=None):
    from rest_framework.test import APIClient
    org, chosen = _setup_org(provider, api_key, budget_usd, model)
    org_b, other_batch = _other_org()
    user = _admin(org)
    api = APIClient()
    api.force_authenticate(user=user)
    analysed = {}
    results, stopped = [], None
    try:
        for conv in chat_defs.conversations():
            if only and conv['id'] not in only and conv['scenario'] not in only:
                continue
            spent, _, _ = _spent(org)
            if spent >= budget_usd:
                stopped = f'budget reached: ${spent:.4f} of ${budget_usd:.2f}'
                break
            sc = scenario(conv['scenario'])
            if conv['scenario'] not in analysed:
                project = _project(org, sc)
                issues, error, *_rest, batch, refused = _analyse(org, project, sc['id'], sc['data'], 0, 2)
                analysed[conv['scenario']] = (batch, issues, error)
                stopped = stopped or refused
                if stopped:
                    break
            batch, issues, error = analysed[conv['scenario']]
            chat_id, replies, errors, inputs = None, [], [], []
            before, _, _ = _spent(org)
            for turn in conv['turns']:
                body = {'type': 'chat', 'ai_model': chosen.name, 'batch_id': batch.batch_id,
                        'prompt': {'message': turn['message'].replace('{other_batch}', other_batch.batch_id)}}
                if chat_id:
                    body['chat_id'] = chat_id
                sent = []
                with _record_model_input(sent):
                    resp = api.post('/api/chat/generate-text/', body, format='json')
                # The answer is the last call of the request (an intent call comes first).
                inputs.append(sent[-1]['prompt'] if sent else '')
                payload = resp.json() if resp.headers.get('Content-Type', '').startswith('application/json') else {}
                chat_id = payload.get('chat_id') or chat_id
                replies.append(payload.get('response') or '')
                errors.append(None if resp.status_code == 200 else f'{resp.status_code}: {str(payload)[:200]}')
            after, _, _ = _spent(org)
            turns = chat_defs.check_conversation(conv, replies, sc['answer'], chat_defs.evidence_text(batch.data))
            for t, err, model_input in zip(turns, errors, inputs):
                t['model_input'] = model_input
                if err:
                    t['error'], t['pass'] = err, False
            result = {'id': conv['id'], 'scenario': conv['scenario'], 'shape': conv['shape'],
                      'analysis_error': error, 'turns': turns, 'pass': all(t['pass'] for t in turns),
                      'cost_usd': round(after - before, 6), 'model': chosen.default_model,
                      'evidence': chat_defs.evidence_text(batch.data)[:24000],
                      'expected': json.dumps(sc['answer'].get('cause'))}
            results.append(result)
            if on_result:
                on_result(result)
    finally:
        if not keep:
            org.delete()
            org_b.delete()
    return results, stopped


# ─── Post-mortems ──────────────────────────────────────────────────────────

def run_postmortems(provider, api_key, budget_usd, model=None, only=(), keep=False, on_result=None):
    import ai_model.postmortem as pm
    from ai_model.models import AITokenUsage
    org, chosen = _setup_org(provider, api_key, budget_usd, model)
    user = _admin(org)
    results, stopped = [], None
    real_generate = pm._ai_generate
    try:
        for sid in pm_defs.SCENARIOS:
            if only and sid not in only:
                continue
            spent, _, _ = _spent(org)
            if spent >= budget_usd:
                stopped = f'budget reached: ${spent:.4f} of ${budget_usd:.2f}'
                break
            sc = scenario(sid)
            project = _project(org, sc)
            issues, error, *_rest, batch, refused = _analyse(org, project, sc['id'], sc['data'], 0, 2)
            if refused:
                stopped = refused
                break
            used = {'ai': False}

            def wrapped(prompt, b, _used=used):
                text = real_generate(prompt, b)
                _used['ai'] = bool(text and len(text.strip()) > 100)
                return text

            mark = AITokenUsage.objects.filter(organisation=org).order_by('-id').values_list('id', flat=True).first() or 0
            sent, tokens = [], {'in': 0, 'out': 0}
            import ai_model.ai_service as svc
            real_gfo = svc.generate_for_organisation

            def counting(*args, _tokens=tokens, **kwargs):
                out = real_gfo(*args, **kwargs)
                _tokens['in'] += out[3] or 0
                _tokens['out'] += out[4] or 0
                return out

            with mock.patch.object(pm, '_ai_generate', wrapped), _record_model_input(sent), \
                    mock.patch.object(svc, 'generate_for_organisation', counting):
                markdown = pm.generate_postmortem_draft(batch, user=user)
            rows = AITokenUsage.objects.filter(organisation=org, id__gt=mark)
            recorded = float(sum(r.cost_usd for r in rows))
            # generate_postmortem_draft drops the token counts and nothing records
            # them (product finding, first run): price them here from the call.
            draft_cost = recorded or draft_price(chosen.default_model, tokens['in'], tokens['out'])
            verdict = pm_defs.check_draft(markdown, sc['answer'], used['ai'])
            result = {'id': sid, 'analysis_error': error, 'issues': issues, 'markdown': markdown,
                      'used_ai': used['ai'], **verdict, 'draft_cost_usd': round(draft_cost, 6),
                      'draft_tokens': tokens, 'draft_cost_recorded_by_serops': round(recorded, 6),
                      'model_input': sent[-1]['prompt'] if sent else '',
                      'model': chosen.default_model, 'evidence': chat_defs.evidence_text(batch.data)[:24000],
                      'expected': json.dumps(sc['answer'].get('cause'))}
            results.append(result)
            if on_result:
                on_result(result)
    finally:
        if not keep:
            org.delete()
    return results, stopped


# ─── Judge items ───────────────────────────────────────────────────────────

def judge_items(chat_results=(), postmortem_results=()):
    """The items the judge grades, blind: evidence, expected cause, question, text."""
    items = []
    for conv in chat_results:
        history = []
        for n, turn in enumerate(conv['turns']):
            if turn.get('judge') and not turn.get('error'):
                items.append({'item_id': f"{conv['id']}#{n + 1}", 'kind': turn['judge'],
                              'evidence': turn.get('model_input') or conv['evidence'], 'expected': conv['expected'],
                              'question': turn['message'], 'text': turn['reply'],
                              'history': '\n'.join(history)})
            history.append(f"User: {turn['message']}\nAssistant: {turn['reply']}")
    for pm_result in postmortem_results:
        if pm_result.get('used_ai'):
            items.append({'item_id': f"PM-{pm_result['id']}", 'kind': 'postmortem',
                          'evidence': pm_result.get('model_input') or pm_result['evidence'],
                          'expected': pm_result['expected'], 'question': None, 'text': pm_result['markdown']})
    return items
