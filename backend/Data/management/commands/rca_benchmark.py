"""
Run the RCA benchmark: incidents with a known root cause, analysed by the
real pipeline with your AI provider, scored by fixed rules.

    RCA_API_KEY=... python manage.py rca_benchmark --provider gemini \\
        --json bench.json --markdown bench.md

Every scenario is one real AI call, billed to the key you pass. The run
stops at --budget-usd (default 1.00), measured from SerOps' own usage
records. It works in a throwaway organisation that is deleted afterwards.
Method and scoring: docs/src/development/rca-benchmark.md.
"""
import json
import os
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from rca_benchmark import report, runner


class Command(BaseCommand):
    help = 'Score root-cause analysis on incidents with a known cause (real AI calls).'

    def add_arguments(self, parser):
        parser.add_argument('--provider', required=True, help='AI provider name, as in Settings (gemini, claude…)')
        parser.add_argument('--api-key-env', default='RCA_API_KEY',
                            help='Environment variable holding the API key (default RCA_API_KEY)')
        parser.add_argument('--set', action='append', choices=sorted(runner.SETS), dest='sets',
                            help='Scenario set; repeat for several (default: held_out and tuned)')
        parser.add_argument('--only', nargs='*', default=[], help='Scenario id prefixes, e.g. h01 s10')
        parser.add_argument('--repeat', type=int, default=1, help='Rounds, to measure consistency')
        parser.add_argument('--budget-usd', type=float, default=1.0, help='Stop once this much is spent')
        parser.add_argument('--pause', type=float, default=0,
                            help='Seconds between calls (free-tier keys are rate limited)')
        parser.add_argument('--keep', action='store_true', help='Keep the benchmark organisation to inspect it')
        parser.add_argument('--json', help='Write every result, with all issues, to this file')
        parser.add_argument('--markdown', help='Write the report to this file')
        parser.add_argument('--list', action='store_true', help='List the scenarios and exit')

    def handle(self, *args, **opts):
        builds = runner.select(opts['sets'] or ['held_out', 'tuned'], opts['only'])
        if opts['list']:
            for b in builds:
                sc = b()
                self.stdout.write(f"{sc['id']:24s} {sc['set']:9s} {sc['category']:15s} {sc['name']}")
            return
        if not builds:
            raise CommandError('No scenario matches.')
        api_key = os.environ.get(opts['api_key_env'])
        if not api_key:
            raise CommandError(f"Set {opts['api_key_env']} to the {opts['provider']} API key.")
        from org_settings.models import AIModelProvider
        if not AIModelProvider.objects.filter(name=opts['provider']).exists():
            names = ', '.join(AIModelProvider.objects.values_list('name', flat=True))
            raise CommandError(f"Unknown provider {opts['provider']!r}. Known: {names}")

        self.stdout.write(f"{len(builds)} scenarios x {opts['repeat']} round(s) with {opts['provider']}, "
                          f"budget ${opts['budget_usd']:.2f}")

        def progress(r):
            sc = r['score']
            verdict = 'ERROR' if not sc else ('PASS' if sc['verdict'] else ('RCA ' if sc['root_cause'] else 'FAIL'))
            failed = ', '.join(k for k, v in sc['checks'].items() if not v) if sc else r['error']
            self.stdout.write(f"{verdict:5s} {r['id']:24s} {len(r['issues'])} issue(s) ${r['cost_usd']:.4f} "
                              f"{r['seconds']}s" + (f'  [{failed}]' if failed else ''))

        results, stopped = runner.run(builds, opts['provider'], api_key, repeat=opts['repeat'],
                                      budget_usd=opts['budget_usd'], pause=opts['pause'], keep=opts['keep'],
                                      on_result=progress)
        from api.version import version_info
        info = version_info()
        models = sorted({str(r['model']) for r in results if r['model'] and not str(r['model']).startswith('FAILED')})
        meta = {'provider': opts['provider'], 'model': ', '.join(models) or 'unknown',
                'version': info['version'], 'commit': info['git_sha'] or 'unknown',
                'date': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'), 'rounds': opts['repeat']}
        if opts['json']:
            with open(opts['json'], 'w') as f:
                json.dump({'meta': meta, 'stopped': stopped, 'summary': report.summarise(results),
                           'results': results}, f, indent=2, default=str)
        md = report.markdown(results, meta, stopped)
        if opts['markdown']:
            with open(opts['markdown'], 'w') as f:
                f.write(md)
        s = report.summarise(results)
        for name in ('held_out', 'tuned'):
            if name in s:
                x = s[name]
                self.stdout.write(f"{name}: root cause {x['root_cause']}/{x['incidents']}, all checks "
                                  f"{x['strict']}/{x['incidents']}, healthy quiet {x['healthy_silent']}/{x['healthy']}, "
                                  f"${x['cost_usd']}")
        if stopped:
            self.stdout.write(self.style.WARNING(f'Stopped early: {stopped}'))
