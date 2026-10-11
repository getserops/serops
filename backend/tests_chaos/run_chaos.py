#!/usr/bin/env python3
"""Chaos-RCA harness — inject a known fault, score what the RCA concluded.

Runs on the HOST (needs kubectl). For each scenario:

  1. clear all faults and let the workload return to baseline
  2. inject
  3. soak, so logs / metrics / traces actually accumulate
  4. create a batch and analyse it with a REAL provider call
  5. score the answer against the scenario's expectations
  6. tear the fault down

Usage:
    ./run_chaos.py                      # every scenario
    ./run_chaos.py --tier A             # one tier
    ./run_chaos.py --only a03 b03       # name prefixes
    ./run_chaos.py --dry-run            # inject + soak, skip the AI call
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from scenarios import SCENARIOS                                  # noqa: E402

CONTEXT = 'serops-val'

# Hard spend ceiling FOR ONE RUN. Enforced against the cost SerOps records per
# call (AITokenUsage.cost_usd), not an estimate — checked after every scenario
# and again before starting the next, so a run stops rather than drifting past
# it.
#
# Measured as a DELTA from the start of the run. It used to compare the ceiling
# against the organisation's lifetime AITokenUsage total, which meant the
# harness quietly became unusable once that total approached the limit. After
# the 2026-10-03 session reached £3.42 of lifetime spend, a fresh run had £0.08
# of apparent headroom: the gate checks before each scenario, so it would have
# run about two and then stopped with "STOPPING: £3.51 spent" — a message about
# money this run never spent, indistinguishable from a bug, whose obvious fix
# would have been to raise the ceiling forever.
BUDGET_LIMIT_GBP = 3.50
USD_PER_GBP = 1.27


def _lifetime_spend_usd():
    """Organisation-wide AITokenUsage total, in USD, before this run begins."""
    pod = backend_pod()
    out = kc('exec', '-n', NS_SEROPS, pod, '--', 'python', 'manage.py', 'shell',
             '-c', ('from ai_model.models import AITokenUsage\n'
                    'from django.db.models import Sum\n'
                    "print(float(AITokenUsage.objects.aggregate(t=Sum('cost_usd'))['t'] or 0))"))
    for line in reversed((out.stdout or '').strip().splitlines()):
        try:
            return float(line.strip())
        except ValueError:
            continue
    return 0.0


def _iso(epoch):
    """UTC ISO-8601 with offset, which the task parses directly."""
    import datetime
    return datetime.datetime.fromtimestamp(
        epoch, tz=datetime.timezone.utc).isoformat()


NS_APP = 'production'
NS_SEROPS = 'serops'
SERVICES = ('checkout', 'api', 'cache', 'loadgen')
HERE = pathlib.Path(__file__).parent


# ---------------------------------------------------------------------------
# kubectl plumbing
# ---------------------------------------------------------------------------

def kc(*args, check=False, timeout=180):
    cmd = ['kubectl', f'--context={CONTEXT}', *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=check, timeout=timeout)


def backend_pod():
    out = kc('get', 'pods', '-n', NS_SEROPS,
             '-l', 'app.kubernetes.io/component=backend',
             '-o', 'jsonpath={.items[0].metadata.name}').stdout.strip()
    if not out:
        sys.exit('no SerOps backend pod found')
    return out


def post_fault(service, payload):
    """POST a fault to every pod of a service, from inside the cluster.

    Executed in the target pod itself — the harness has no route to a
    ClusterIP service from the host, and port-forwarding one service per
    scenario is slower and flakier than an exec.
    """
    body = json.dumps(payload).replace("'", "")
    snippet = (
        'import json,requests;'
        f'requests.post("http://127.0.0.1:8080/fault",json=json.loads({body!r}),timeout=5)'
    )
    return kc('exec', '-n', NS_APP, f'deploy/{service}', '--',
              'python', '-c', snippet)


def clear_faults():
    for svc in SERVICES:
        if svc == 'loadgen':
            continue
        kc('exec', '-n', NS_APP, f'deploy/{svc}', '--', 'python', '-c',
           'import requests;requests.post("http://127.0.0.1:8080/fault/clear",timeout=5)')


def reset_workload():
    """Return the workload to a known-good baseline between scenarios.

    Faults that mutate the Deployment (env overrides, replica counts) survive
    a /fault/clear, so they are undone explicitly. Without this, scenario N+1
    inherits N's damage and its score is meaningless.
    """
    kc('set', 'env', 'deploy/api', '-n', NS_APP,
       'DOWNSTREAM_URL=http://cache.production.svc.cluster.local:8080',
       'POOL_SIZE-')
    kc('scale', 'deploy/cache', '-n', NS_APP, '--replicas=1')
    kc('scale', 'deploy/kps-kube-state-metrics', '-n', 'monitoring', '--replicas=1')
    kc('scale', 'statefulset/prometheus-kps-kube-prometheus-stack-prometheus',
       '-n', 'monitoring', '--replicas=1')
    clear_faults()
    wait_for_stable_workload()


def wait_for_stable_workload(quiet_seconds=45, timeout=240):
    """Block until no workload container has restarted for `quiet_seconds`.

    Clearing a fault stops the CAUSE, not its aftermath. A container that was
    OOMKilled during the previous scenario keeps crashlooping for a while, and
    those restarts land inside the NEXT scenario's window — where they are
    genuinely in-window, so window-bounding the lifecycle query cannot filter
    them out and should not.

    Measured: the latency scenario, run straight after the memory-exhaustion
    one, came back with a narrative led by "api was OOMKilled" and "cache
    repeatedly OOMKilled (4 restarts)" — true of the cluster, and nothing to do
    with the 1.5s delay under test. The latency finding was demoted to third
    place. The scenario still passed its checks, which is exactly the kind of
    green run the README warns is necessary but not sufficient.

    So the harness waits for the cluster to go quiet before it starts measuring.
    On timeout it proceeds and says so rather than aborting the run — a noisy
    measurement beats no measurement, as long as the noise is declared.
    """
    # 45s covers a CrashLoopBackOff cycle (the backoff starts at 10s and grows),
    # which is what actually needs detecting. Longer only buys certainty about a
    # cluster that has already gone quiet, at ~1 minute per scenario across a
    # full run.
    deadline = time.time() + timeout
    last_counts = None
    quiet_since = None
    while time.time() < deadline:
        counts = restart_counts()
        if counts == last_counts:
            if quiet_since is None:
                quiet_since = time.time()
            elif time.time() - quiet_since >= quiet_seconds:
                return True
        else:
            quiet_since = None
            last_counts = counts
        time.sleep(5)
    print(f'    WARNING: workload still restarting after {timeout}s '
          f'({last_counts}); proceeding — treat this scenario as contaminated')
    return False


def restart_counts():
    """Restart count per container across the workload namespace."""
    return kc('get', 'pods', '-n', NS_APP, '-o',
              'jsonpath={range .items[*]}{range .status.containerStatuses[*]}'
              '{.name}={.restartCount} {end}{end}').stdout.strip()


def apply_injection(inject):
    """Apply one scenario's injection list, honouring the pseudo-services."""
    for target, payload in inject:
        if target == '__scale__':
            kc('scale', f'deploy/{payload["deployment"]}', '-n', NS_APP,
               f'--replicas={payload["replicas"]}')
        elif target == '__deploy__':
            # A real rollout, so Sentinel sees deployment_detected.
            kc('set', 'env', f'deploy/{payload["deployment"]}', '-n', NS_APP,
               f'CHAOS_RELEASE={int(time.time())}')
        elif target == '__break_metrics__':
            kc('scale', 'statefulset/prometheus-kps-kube-prometheus-stack-prometheus',
               '-n', 'monitoring', '--replicas=0')
        elif '__env__' in payload:
            args = [f'{k}={v}' for k, v in payload['__env__'].items()]
            kc('set', 'env', f'deploy/{target}', '-n', NS_APP, *args)
        else:
            post_fault(target, payload)


def wait_rollout(deployment, ns=NS_APP, timeout=120):
    kc('rollout', 'status', f'deploy/{deployment}', '-n', ns,
       f'--timeout={timeout}s', timeout=timeout + 20)


# ---------------------------------------------------------------------------
# Analysis + scoring
# ---------------------------------------------------------------------------

def analyse(window_start=None, window_end=None):
    pod = backend_pod()
    kc('cp', str(HERE / '_analyze_once.py'),
       f'{NS_SEROPS}/{pod}:/tmp/_analyze_once.py')
    # env passed through `env` rather than kubectl, which has no --env flag
    # for exec; this keeps the window out of the shell-quoted snippet.
    prelude = (
        f'import os;'
        f'os.environ["CHAOS_WINDOW_START"]={(window_start or "")!r};'
        f'os.environ["CHAOS_WINDOW_END"]={(window_end or "")!r};'
        f'os.environ["CHAOS_RESET_STATE"]="1";'
    )
    res = kc('exec', '-n', NS_SEROPS, pod, '--', 'python', 'manage.py',
             'shell', '-c',
             prelude + "exec(open('/tmp/_analyze_once.py').read())",
             timeout=900)
    # The pod prints one JSON line; Django may print warnings around it.
    for line in reversed(res.stdout.splitlines()):
        line = line.strip()
        if line.startswith('{') and line.endswith('}'):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return {'ok': False, 'error': 'no JSON from pod',
            'stderr': res.stderr[-400:], 'stdout': res.stdout[-400:]}


def score(scenario, result):
    """Per-dimension pass/fail. Every check is reported, not just the total,
    so a partial answer is visible rather than collapsed into one bit."""
    expect = scenario['expect']
    haystack = ' '.join([
        result.get('narrative') or '',
        *[f"{i.get('description','')} {i.get('root_cause','')} {i.get('issue_type','')}"
          for i in result.get('issues') or []],
    ]).lower()
    components = [str(i.get('component') or '').lower()
                  for i in result.get('issues') or []]
    checks = {}

    if 'root_cause_any' in expect:
        hit = [p for p in expect['root_cause_any'] if p.lower() in haystack]
        checks['root_cause'] = (bool(hit), f'matched={hit}' if hit
                                else f'none of {expect["root_cause_any"]}')

    if 'component_any' in expect:
        hit = [c for c in expect['component_any']
               if any(c.lower() in comp for comp in components)]
        checks['component'] = (bool(hit), f'matched={hit}' if hit
                               else f'blamed={components}')

    if 'must_not_say' in expect:
        bad = [p for p in expect['must_not_say'] if p.lower() in haystack]
        checks['no_misblame'] = (not bad, f'FOUND={bad}' if bad else 'clean')

    if expect.get('sentinel_analysed'):
        got = result.get('sentinel_decision')
        # 'first' and 'alert' both mean Sentinel let the AI run. State is
        # reset per scenario, so 'first' is the expected label; the thing
        # under test is that a real fault was not gated away as quiet.
        checks['sentinel'] = (got in ('first', 'alert'),
                              f'{got} (want first|alert, i.e. not gated)')

    if 'min_issues' in expect:
        n = len(result.get('issues') or [])
        checks['issue_count'] = (n >= expect['min_issues'],
                                 f'{n} (want >= {expect["min_issues"]})')

    if 'max_issues' in expect:
        n = len(result.get('issues') or [])
        checks['issue_count'] = (n <= expect['max_issues'],
                                 f'{n} (want <= {expect["max_issues"]})')

    passed = all(ok for ok, _ in checks.values())
    return passed, checks


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_one(scenario, dry_run=False):
    name = scenario['name']
    print(f'\n{"=" * 74}\n[{scenario["tier"]}] {name}\n  {scenario["description"]}\n{"=" * 74}')

    print('  resetting to baseline...')
    reset_workload()
    for svc in ('cache', 'api', 'checkout'):
        wait_rollout(svc)
    time.sleep(20)                      # let the baseline register in metrics

    print(f'  injecting {len(scenario["inject"])} fault(s)...')
    # Window opens at injection, so the batch sees this scenario's signals
    # and nothing from the one before it.
    window_start = _iso(time.time() - 5)
    apply_injection(scenario['inject'])

    soak = scenario['soak']
    print(f'  soaking {soak}s so signals accumulate...')
    time.sleep(soak)
    window_end = _iso(time.time())

    if dry_run:
        print('  [dry-run] skipping the AI call')
        return {'name': name, 'tier': scenario['tier'], 'skipped': True}

    print(f'  creating batch + analysing (real provider call)')
    print(f'    window {window_start} -> {window_end}')
    result = analyse(window_start, window_end)

    if not result.get('ok'):
        print(f'  HARNESS/PIPELINE ERROR: {result.get("error")}')
        outcome = {'name': name, 'tier': scenario['tier'], 'passed': False,
                   'error': result.get('error'), 'raw': result}
    else:
        passed, checks = score(scenario, result)
        print(f'  logs={result.get("logs")} '
              f'sentinel={result.get("sentinel_decision")}{result.get("sentinel_triggers")} '
              f'model={result.get("model_name")}')
        m = result.get('metrics') or {}
        print(f'  metrics: cpu_pts={m.get("cpu_points")} mem_pts={m.get("mem_points")} '
              f'anomalies={m.get("anomalies")}  traces={result.get("traces")}')
        print(f'  narrative: {(result.get("narrative") or "")[:220]}')
        for issue in (result.get('issues') or [])[:4]:
            print(f'    [{issue.get("severity")}] {issue.get("component")} / '
                  f'{issue.get("issue_type")}: {(issue.get("description") or "")[:110]}')
        print(f'  --- {"PASS" if passed else "FAIL"} ---')
        for check, (ok, detail) in checks.items():
            print(f'    {"ok  " if ok else "FAIL"} {check}: {detail}')
        spend = result.get('spend') or {}
        gbp = spend.get('cumulative_usd', 0.0) / USD_PER_GBP
        print(f'  spend: this scenario ${spend.get("this_scenario_usd", 0):.4f} | '
              f'cumulative ${spend.get("cumulative_usd", 0):.4f} '
              f'(~£{gbp:.2f} of £{BUDGET_LIMIT_GBP:.2f}) | '
              f'tokens {spend.get("tokens_in", 0)}in/{spend.get("tokens_out", 0)}out')
        outcome = {'name': name, 'tier': scenario['tier'], 'passed': passed,
                   'spend': spend,
                   'checks': {k: {'ok': v[0], 'detail': v[1]} for k, v in checks.items()},
                   'narrative': result.get('narrative'),
                   'issues': result.get('issues'),
                   'sentinel': result.get('sentinel_decision'),
                   'sentinel_triggers': result.get('sentinel_triggers'),
                   'logs': result.get('logs'),
                   'metrics': result.get('metrics'),
                   'traces': result.get('traces'),
                   'model': result.get('model_name')}

    print('  tearing down...')
    reset_workload()
    return outcome


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tier', action='append', help='A, B or C (repeatable)')
    ap.add_argument('--only', nargs='*', help='scenario name prefixes')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--out', default=str(HERE / 'results.json'))
    ap.add_argument('--resume', action='store_true',
                    help='keep scenarios already scored in --out and skip them')
    args = ap.parse_args()

    selected = SCENARIOS
    if args.tier:
        tiers = {t.upper() for t in args.tier}
        selected = [s for s in selected if s['tier'] in tiers]
    if args.only:
        selected = [s for s in selected
                    if any(s['name'].startswith(p) for p in args.only)]
    if not selected:
        sys.exit('no scenarios matched')

    # Results are written after EVERY scenario, not once at the end. A full run
    # is over an hour of soak and a stop partway — a budget ceiling, Ctrl-C, or
    # a fix worth applying immediately — used to discard every scenario already
    # paid for. `--resume` then keeps what is in --out and runs only the rest,
    # so an interrupted run costs its remaining scenarios rather than all of
    # them.
    out_path = pathlib.Path(args.out)
    # Lifetime spend before this run starts, so the ceiling applies to what
    # THIS run costs.
    baseline_usd = _lifetime_spend_usd()
    print(f'lifetime AI spend before this run: ${baseline_usd:.4f}')
    results = []
    if args.resume and out_path.exists():
        try:
            results = json.loads(out_path.read_text())
            done = {r['name'] for r in results if r.get('name')}
            selected = [s for s in selected if s['name'] not in done]
            print(f'resuming: {len(done)} scenario(s) already scored, '
                  f'{len(selected)} to go')
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f'--resume: could not read {args.out} ({exc}); starting fresh')
            results = []
    if not selected:
        print('nothing left to run')

    print(f'running {len(selected)} scenario(s)  budget ceiling £{BUDGET_LIMIT_GBP:.2f}')
    for scenario in selected:
        spent_gbp = max(
            (r.get('spend', {}).get('cumulative_usd', 0.0) - baseline_usd
             for r in results),
            default=0.0) / USD_PER_GBP
        if spent_gbp >= BUDGET_LIMIT_GBP:
            print(f'\nSTOPPING: £{spent_gbp:.2f} spent, ceiling is '
                  f'£{BUDGET_LIMIT_GBP:.2f}. {scenario["name"]} and the rest '
                  f'were not run.')
            break
        try:
            results.append(run_one(scenario, dry_run=args.dry_run))
        except KeyboardInterrupt:
            print('\ninterrupted — restoring workload')
            out_path.write_text(json.dumps(results, indent=2))
            reset_workload()
            break
        except Exception as exc:                        # noqa: BLE001
            print(f'  SCENARIO CRASHED: {type(exc).__name__}: {exc}')
            results.append({'name': scenario['name'], 'tier': scenario['tier'],
                            'passed': False, 'error': f'{type(exc).__name__}: {exc}'})
            reset_workload()
        out_path.write_text(json.dumps(results, indent=2))

    out_path.write_text(json.dumps(results, indent=2))

    scored = [r for r in results if 'passed' in r]
    print(f'\n{"=" * 74}\nSUMMARY\n{"=" * 74}')
    for r in results:
        if r.get('skipped'):
            mark = 'skip'
        else:
            mark = 'PASS' if r.get('passed') else 'FAIL'
        print(f'  {mark:4}  [{r["tier"]}] {r["name"]}'
              + (f'   ({r["error"]})' if r.get('error') else ''))
    if scored:
        ok = sum(1 for r in scored if r['passed'])
        print(f'\n  {ok}/{len(scored)} passed')
        for tier in ('A', 'B', 'C'):
            t = [r for r in scored if r['tier'] == tier]
            if t:
                print(f'    tier {tier}: {sum(1 for r in t if r["passed"])}/{len(t)}')
    spends = [r.get('spend', {}).get('cumulative_usd', 0.0) - baseline_usd
              for r in results if r.get('spend')]
    if spends:
        total = max(spends)
        print(f'\n  measured spend: ${total:.4f} (~£{total / USD_PER_GBP:.2f}) '
              f'of £{BUDGET_LIMIT_GBP:.2f} ceiling')
    print(f'\n  full results: {args.out}')
    return 0 if scored and all(r['passed'] for r in scored) else 1


if __name__ == '__main__':
    sys.exit(main())
