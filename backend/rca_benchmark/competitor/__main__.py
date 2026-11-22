"""
    cd backend
    docker build -t serops-bench/holmesgpt:0.46.0 -f rca_benchmark/competitor/Dockerfile.holmesgpt rca_benchmark/competitor
    python3 -m rca_benchmark.competitor --tool holmesgpt --env-file ~/anthropic.env \\
        --set held_out_v2 [--only v01 v03] [--budget-usd 2] [--json out.json] [--markdown out.md] [--dry-run]

``--env-file`` holds ANTHROPIC_API_KEY=... (passed to the container, never
printed). No Django and no database: scenarios, keys and scoring are plain
Python.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

from .. import held_out, held_out_v2, held_out_v3, tuned
from ..report import _pct, summarise
from . import HOLMES_VERSION, K8SGPT_NOT_COMPARABLE, MODEL, run

SETS = {'held_out': held_out.SCENARIOS, 'held_out_v2': held_out_v2.SCENARIOS,
        'held_out_v3': held_out_v3.SCENARIOS, 'tuned': tuned.SCENARIOS}


def markdown(results, stopped):
    s = summarise(results)
    lines = [f'# Competitor run: HolmesGPT {HOLMES_VERSION} ({MODEL})', '',
             f"Run {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, {len(results)} scenario runs. "
             'Same scenarios, keys and scoring as SerOps. HolmesGPT gets the scenario evidence as files, '
             'its tools off: this measures reasoning over the same evidence, not data collection.', '']
    if stopped:
        lines += [f'**Stopped early:** {stopped}.', '']
    for name, row in s.items():
        if name == 'all' or not isinstance(row, dict) or 'incidents' not in row:
            continue
        lines += [f'## {name}', '',
                  f"- Root cause correct (top issue: service, cause, commit): {_pct(row['root_cause'], row['incidents'])}",
                  f"- All checks: {_pct(row['strict'], row['incidents'])}",
                  f"- Healthy windows left quiet: {_pct(row['healthy_silent'], row['healthy'])}",
                  f"- Not analysed (error or unreadable answer; left out above): {row['errors']}",
                  f"- Cost (USD, SerOps prices): ${row['cost_usd']}", '']
    lines += ['| Scenario | Round | Root cause | All checks | Top issue | Tools called | Error |',
              '|---|---|---|---|---|---|---|']
    for r in results:
        sc = r['score'] or {}
        top = (r['issues'] or [{}])[0]
        tools = ', '.join(sorted(set(r['tool_calls']))) or 'none'
        lines.append(f"| {r['id']} | {r['round']} | {sc.get('root_cause', '–')} | {sc.get('verdict', '–')} | "
                     f"{(top.get('component') or '')[:40]} | {tools[:60]} | {(r['error'] or '')[:60]} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description='Score another RCA tool on the SerOps benchmark scenarios.')
    ap.add_argument('--tool', required=True, choices=['holmesgpt', 'k8sgpt'])
    ap.add_argument('--env-file', help='File with ANTHROPIC_API_KEY=..., passed to the container')
    ap.add_argument('--set', action='append', dest='sets', choices=sorted(SETS))
    ap.add_argument('--only', nargs='*', default=[])
    ap.add_argument('--repeat', type=int, default=1)
    ap.add_argument('--budget-usd', type=float, default=1.0)
    ap.add_argument('--json')
    ap.add_argument('--markdown')
    ap.add_argument('--mode', choices=['default', 'evidence-only'], default='default',
                    help="'default': HolmesGPT's documented defaults (published runs); 'evidence-only': its "
                         'internet, connectivity and Prometheus toolsets off')
    ap.add_argument('--dry-run', action='store_true', help='Write the evidence and build the command; call nothing')
    args = ap.parse_args(argv)
    if args.tool == 'k8sgpt':
        print(K8SGPT_NOT_COMPARABLE)
        return 2
    if not args.env_file and not args.dry_run:
        ap.error('--env-file is required unless --dry-run')
    builds = [b for name in (args.sets or ['held_out_v2']) for b in SETS[name]]
    if args.only:
        builds = [b for b in builds if any(b.__name__.startswith(o) for o in args.only)]

    def show(r):
        sc = r['score'] or {}
        print(f"{r['id']:<42} root_cause={sc.get('root_cause', '-')!s:<5} checks={sc.get('verdict', '-')!s:<5} "
              f"${r['cost_usd']:.4f} {r['seconds']}s tools={len(r['tool_calls'])} {r['error'] or ''}", flush=True)

    results, stopped = run(builds, args.env_file, budget_usd=args.budget_usd, repeat=args.repeat,
                           dry_run=args.dry_run, on_result=show, mode=args.mode)
    if args.json:
        with open(args.json, 'w') as f:
            json.dump({'meta': {'tool': 'holmesgpt', 'version': HOLMES_VERSION, 'model': MODEL, 'mode': args.mode},
                       'stopped': stopped, 'results': results}, f, indent=1, default=str)
    if args.markdown:
        with open(args.markdown, 'w') as f:
            f.write(markdown(results, stopped))
    print(f"spent ${sum(r['cost_usd'] for r in results):.4f}" + (f'; stopped: {stopped}' if stopped else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
