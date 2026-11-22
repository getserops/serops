"""
Score other RCA tools on the same scenarios, keys and rules as SerOps.

Method (written before any result was seen):

* Evidence. Each scenario's ``data`` is what SerOps receives for the
  window. The tool gets the same, as files: ``logs.txt`` (one line per log
  record: time, level, service, host, message), ``changes.txt`` (each commit
  with time, author, message and diffs), and every other source as
  ``<name>.json`` unchanged (metrics summary, traces summary, CI/CD logs,
  operator context, the triggering alert). Nothing is added, nothing is
  removed.
* Question. One fixed instruction (``QUESTION``) asks for the incidents in
  the window and their root cause, as JSON with the fields the scoring
  reads: severity, confidence, component, affected services, root cause,
  description, recommendation, commit at fault. SerOps answers the same
  fields through its own prompt. No model reads or grades the answers.
* Scoring. ``rca_benchmark.scoring.score``, unchanged, on the parsed issues.
  An answer that is not valid JSON is a run with an error, reported and
  counted apart, as SerOps runs with a provider error are.
* Model. The tool runs on the same model as SerOps (claude-sonnet-5-5),
  through its own provider settings, with the same key.

Tools:

* HolmesGPT (``holmesgpt``), pinned in Dockerfile.holmesgpt. Run with
  ``holmes ask --no-interactive -f <files>`` and, by default, HolmesGPT's
  documented defaults: no config file, its default toolsets. In the
  container there is no cluster, kubeconfig, CLI or token, so the toolsets
  that need one have nothing to call; the tools it did call are recorded per
  scenario. It normally investigates by calling such tools; here it gets the
  evidence as files, so this measures its reasoning over the same evidence,
  not its data collection. That is stated next to every result.
* k8sgpt: not scored on these scenarios. Its analyzers read live
  Kubernetes objects through the API server (pods, events, deployments...);
  it has no input for logs, metrics, traces or commits, so synthetic
  scenarios cannot be given to it. The closest honest comparison is on a
  live estate during an incident, which this module does not do.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

from ..scoring import score

HOLMES_IMAGE = 'serops-bench/holmesgpt:0.46.0'
HOLMES_VERSION = '0.46.0'
MODEL = 'claude-sonnet-5-5'
# Same prices as SerOps' usage records (ai_model pricing for claude-sonnet-5-5):
# per million tokens, input 2, cache write 2.5, cache read 0.2, output 10.
PRICE = {'input': 2.0, 'cache_write': 2.5, 'cache_read': 0.2, 'output': 10.0}

K8SGPT_NOT_COMPARABLE = (
    'k8sgpt reads live Kubernetes objects through the API server and has no input for logs, metrics, '
    'traces or commits; the synthetic scenarios cannot be given to it. Not scored.')

QUESTION = (
    'These files hold what was observed in one production environment during a 30-minute window: '
    'application logs (logs.txt), recent code changes with their diffs (changes.txt), and when present '
    'other sources as JSON (metrics summary, trace summary, CI/CD logs, operator notes, the alert that '
    'fired). Find every incident in the window and its root cause; if nothing is wrong, say so with no '
    'issue above INFO. Answer with only a JSON object: {"issues": [{"severity": "CRITICAL|WARNING|INFO", '
    '"confidence": "HIGH|MEDIUM|LOW", "component": "service at fault", "affected_services": ["..."], '
    '"root_cause": "...", "description": "...", "recommendation": "...", '
    '"linked_commits": "sha of the commit at fault, or empty"}]}, most important issue first.')

SEVERITIES = ('CRITICAL', 'WARNING', 'INFO')
CONFIDENCES = ('HIGH', 'MEDIUM', 'LOW')


class AnswerError(ValueError):
    """The tool's answer cannot be read as issues."""


# ─── Evidence ───────────────────────────────────────────────────────────

def _log_line(record):
    src = record.get('_source', record)
    service = (src.get('service') or {}).get('name') if isinstance(src.get('service'), dict) else src.get('service')
    host = (src.get('host') or {}).get('name') if isinstance(src.get('host'), dict) else src.get('host')
    return (f"{src.get('@timestamp', '')} {src.get('log_level', '')} {service or ''}"
            f"{f' host={host}' if host else ''}: {src.get('message', '')}")


def _changes_text(changes):
    out = []
    for c in changes:
        out.append(f"commit {c.get('sha')} {c.get('timestamp')} author={c.get('author')} branch={c.get('branch')}"
                   f"{' service=' + c['service_name'] if c.get('service_name') else ''}\n    {c.get('message')}")
        for f in c.get('files') or []:
            out.append(f"--- {f.get('path')}\n{f.get('diff', '')}")
    return '\n'.join(out) + '\n'


def evidence_files(data):
    """{filename: text} for one window's data: everything SerOps gets."""
    files = {}
    for key, value in data.items():
        if key == 'logs':
            files['logs.txt'] = '\n'.join(_log_line(r) for r in value) + '\n'
        elif key == 'code_changes':
            files['changes.txt'] = _changes_text(value)
        else:
            files[f'{key}.json'] = json.dumps(value, indent=1, ensure_ascii=False, default=str) + '\n'
    return files


# ─── Answers ────────────────────────────────────────────────────────────

def _json_candidates(text):
    fenced = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    if fenced:
        return fenced
    start = text.find('{')
    return [text[start:text.rfind('}') + 1]] if start >= 0 else []


def parse_issues(text):
    """The issues list from a tool's answer, normalised to the dicts the
    scoring reads. Raises AnswerError when there is no readable JSON."""
    for candidate in reversed(_json_candidates(str(text or ''))):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        issues = obj.get('issues') if isinstance(obj, dict) else None
        if not isinstance(issues, list):
            continue
        out = []
        for i in issues:
            if not isinstance(i, dict):
                continue
            sev = str(i.get('severity') or '').upper()
            conf = str(i.get('confidence') or '').upper()
            affected = i.get('affected_services') or []
            commits = i.get('linked_commits') or ''
            out.append({
                'severity': sev if sev in SEVERITIES else 'UNKNOWN',
                'confidence': conf if conf in CONFIDENCES else 'UNKNOWN',
                'component': str(i.get('component') or ''),
                'affected_services': [str(a) for a in affected] if isinstance(affected, list) else [str(affected)],
                'root_cause': str(i.get('root_cause') or ''),
                'description': str(i.get('description') or ''),
                'recommendation': str(i.get('recommendation') or ''),
                'linked_commits': ' '.join(map(str, commits)) if isinstance(commits, list) else str(commits),
                'reasoning': '',
            })
        return out
    raise AnswerError('no JSON object with an "issues" list in the answer')


def cost_usd(usage):
    """USD at SerOps' prices from HolmesGPT's token counts."""
    prompt = int(usage.get('prompt_tokens') or 0)
    write = int(usage.get('cache_creation_tokens') or 0)
    read = int(usage.get('cached_tokens') or 0)
    plain = max(prompt - write - read, 0)
    out = int(usage.get('completion_tokens') or 0)
    return round((plain * PRICE['input'] + write * PRICE['cache_write'] + read * PRICE['cache_read']
                  + out * PRICE['output']) / 1e6, 6)


# ─── Running HolmesGPT ──────────────────────────────────────────────────

# 'default': HolmesGPT as documented, no config file, its default toolsets
# (those without a cluster, CLI or token have nothing to call and say so).
# 'evidence-only': our holmes-config.yaml turns off the internet,
# connectivity and Prometheus toolsets. The published run uses 'default'.
MODES = ('default', 'evidence-only')


def holmes_command(evidence_dir, out_dir, env_file, files, image=HOLMES_IMAGE, model=MODEL, mode='default'):
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}')
    cmd = ['docker', 'run', '--rm', '--env-file', env_file, '-v', f'{evidence_dir}:/ev:ro', '-v', f'{out_dir}:/out']
    ask = ['holmes', 'ask']
    if mode == 'evidence-only':
        config = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'holmes-config.yaml')
        cmd += ['-v', f'{config}:/cfg/config.yaml:ro']
        ask += ['--config', '/cfg/config.yaml']
    cmd += [image] + ask + ['--no-interactive', '--no-echo', '--model', f'anthropic/{model}',
                            '--json-output-file', '/out/out.json']
    for name in sorted(files):
        cmd += ['-f', f'/ev/{name}']
    return cmd + [QUESTION]


def _tool_names(result):
    names = []
    for call in result.get('tool_calls') or []:
        if isinstance(call, dict):
            names.append(str(call.get('tool_name') or call.get('name') or call.get('description') or '?')[:80])
    return names


def run_holmes(data, env_file, timeout=600, image=HOLMES_IMAGE, model=MODEL, dry_run=False, runner=subprocess.run,
               mode='default'):
    """(issues, error, seconds, cost, tokens_in, tokens_out, tools called) for one window."""
    work = tempfile.mkdtemp(prefix='rca-competitor-')
    try:
        ev, out = os.path.join(work, 'ev'), os.path.join(work, 'out')
        os.makedirs(ev)
        os.makedirs(out)
        os.chmod(out, 0o777)        # the container writes as its own user
        files = evidence_files(data)
        for name, text in files.items():
            with open(os.path.join(ev, name), 'w') as f:
                f.write(text)
        cmd = holmes_command(ev, out, env_file, files, image, model, mode)
        if dry_run:
            return [], 'dry run: not executed', 0.0, 0.0, 0, 0, []
        started = time.monotonic()
        try:
            proc = runner(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return [], f'timed out after {timeout}s', float(timeout), 0.0, 0, 0, []
        seconds = round(time.monotonic() - started, 1)
        path = os.path.join(out, 'out.json')
        if proc.returncode != 0 or not os.path.exists(path):
            text = ' '.join((proc.stderr or '') .split() + (proc.stdout or '').split())
            hit = next((m for m in ACCOUNT_REFUSED if m in text), None)
            tail = hit or text[-300:]
            return [], f'holmes exited {proc.returncode}: {tail}', seconds, 0.0, 0, 0, []
        with open(path) as f:
            result = json.load(f)
        cost = cost_usd(result)
        tin, tout = int(result.get('prompt_tokens') or 0), int(result.get('completion_tokens') or 0)
        calls = _tool_names(result)
        try:
            issues = parse_issues(result.get('result'))
        except AnswerError as exc:
            return [], str(exc), seconds, cost, tin, tout, calls
        return issues, None, seconds, cost, tin, tout, calls
    finally:
        shutil.rmtree(work, ignore_errors=True)


# The provider refuses every call until someone acts (as runner.ACCOUNT_REFUSED):
# stop instead of recording a row of identical errors.
ACCOUNT_REFUSED = ('reached your specified API usage limits', 'credit balance is too low',
                   'authentication_error', 'invalid x-api-key')


def run(builds, env_file, budget_usd=1.0, repeat=1, dry_run=False, on_result=None, analyse=None, mode='default'):
    """Like runner.run, for HolmesGPT. Returns (results, stopped)."""
    analyse = analyse or (lambda data: run_holmes(data, env_file, dry_run=dry_run, mode=mode))
    results, stopped, spent = [], None, 0.0
    for rnd in range(repeat):
        for build in builds:
            if spent >= budget_usd:
                stopped = f'budget reached: spent ${spent:.4f} of ${budget_usd:.2f}'
                break
            sc = build()
            if 'batches' in sc:
                raise ValueError(f"{sc['id']}: multi-window scenarios are not supported by the competitor run")
            issues, error, seconds, cost, tin, tout, calls = analyse(sc['data'])
            spent += cost
            sc_score = None if error else score(sc['answer'], issues)
            if sc_score and sc_score['kind'] == 'healthy':
                sc_score['root_cause'] = sc_score['lenient'] = sc_score['verdict']
            result = {'id': sc['id'], 'set': sc['set'], 'category': sc['category'], 'name': sc['name'],
                      'round': rnd + 1, 'provider': f'holmesgpt {HOLMES_VERSION}', 'dropped': [],
                      'model': MODEL, 'ai_called': tin > 0, 'error': error, 'seconds': seconds,
                      'cost_usd': cost, 'tokens_input': tin, 'tokens_output': tout, 'tool_calls': calls, 'mode': mode,
                      'issues': issues, 'answer': sc['answer'], 'score': sc_score}
            results.append(result)
            if on_result:
                on_result(result)
            refused = next((m for m in ACCOUNT_REFUSED if m in str(error or '')), None)
            if refused:
                stopped = f'provider refused the account ({refused})'
                break
        if stopped:
            break
    return results, stopped
