"""
Phase 3 track 4: alerts, chat and post-mortems through the real code paths,
and the blind judge (see rca_benchmark/track4).

    manage.py rca_track4 estimate
    manage.py rca_track4 alerts     --provider claude --model claude-sonnet-5-5 --budget-usd 1.5 --rounds 2 --json a.json
    manage.py rca_track4 chat       --provider claude --model claude-sonnet-5-5 --budget-usd 3.5 --json c.json
    manage.py rca_track4 postmortem --provider claude --model claude-sonnet-5-5 --budget-usd 1.5 --json p.json
    manage.py rca_track4 judge      --in c.json p.json --budget-usd 4 --json j.json   (key in JUDGE_API_KEY)
    manage.py rca_track4 sample     --in j.json --json hand-check.json

Run it on a throwaway database only, as rca_benchmark: every run works in an
organisation created for it and deleted afterwards. The AI key is read from
an environment variable, never from the command line.
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Phase 3 track 4: alerts, chat, post-mortems, blind judge'

    def add_arguments(self, parser):
        parser.add_argument('track', choices=['estimate', 'alerts', 'chat', 'postmortem', 'judge', 'sample'])
        parser.add_argument('--provider', default='claude')
        parser.add_argument('--model')
        parser.add_argument('--api-key-env', default='RCA_API_KEY')
        parser.add_argument('--judge-key-env', default='JUDGE_API_KEY')
        parser.add_argument('--budget-usd', type=float, default=1.0)
        parser.add_argument('--rounds', type=int, default=2, help='alerts only')
        parser.add_argument('--only', nargs='*', default=[])
        parser.add_argument('--keep', action='store_true')
        parser.add_argument('--in', nargs='*', dest='inputs', default=[], help='judge / sample: result files')
        parser.add_argument('--json', help='write results here')

    def _write(self, path, payload):
        if path:
            with open(path, 'w') as fh:
                json.dump(payload, fh, indent=1, default=str)
            self.stdout.write(f'wrote {path}')

    def handle(self, *args, **opts):
        from rca_benchmark.track4 import cost, judge, runners
        track = opts['track']
        if track == 'estimate':
            rows, total = cost.estimate()
            for name, calls, model, usd in rows:
                self.stdout.write(f'{name:32} {calls:4} x {model:18} ${usd:.2f}')
            self.stdout.write(f'{"total":32} ${total:.2f}')
            return
        if track in ('judge', 'sample'):
            loaded = []
            for path in opts['inputs']:
                with open(path) as fh:
                    loaded.append(json.load(fh))
            if track == 'sample':
                items = [i for doc in loaded for i in doc.get('items', [])]
                picked = judge.hand_sample(items)
                self._write(opts['json'], {'hand_check': picked, 'of': len(items)})
                self.stdout.write(f'{len(picked)} of {len(items)} items for a hand check')
                return
            chat_results = [r for doc in loaded if doc.get('track') == 'chat' for r in doc['results']]
            pm_results = [r for doc in loaded if doc.get('track') == 'postmortem' for r in doc['results']]
            items = runners.judge_items(chat_results, pm_results)
            key = os.environ.get(opts['judge_key_env'])
            if not key:
                raise CommandError(f"Set {opts['judge_key_env']} to the Anthropic API key for the judge.")
            graded, spent = judge.grade_all(items, key, opts['budget_usd'])
            passed = sum(1 for i in graded if (i['judge'].get('verdict') or {}).get('overall'))
            errors = sum(1 for i in graded if i['judge'].get('error'))
            self._write(opts['json'], {'track': 'judge', 'model': judge.MODEL, 'effort': judge.EFFORT,
                                       'cost_usd': spent, 'items': graded})
            self.stdout.write(f'judge: {passed}/{len(graded)} pass, {errors} not graded, ${spent:.4f}')
            return

        api_key = os.environ.get(opts['api_key_env'])
        if not api_key:
            raise CommandError(f"Set {opts['api_key_env']} to the {opts['provider']} API key.")

        def show(result):
            self.stdout.write(f"{result['id']:>14} {'PASS' if result['pass'] else 'FAIL'}  ${result.get('cost_usd', result.get('draft_cost_usd', 0)):.4f}")

        common = dict(provider=opts['provider'], api_key=api_key, budget_usd=opts['budget_usd'], model=opts['model'],
                      only=tuple(opts['only']), keep=opts['keep'], on_result=show)
        if track == 'alerts':
            results, stopped = runners.run_alerts(rounds=opts['rounds'], **common)
        elif track == 'chat':
            results, stopped = runners.run_chat(**common)
        else:
            results, stopped = runners.run_postmortems(**common)
        passed = sum(1 for r in results if r['pass'])
        self._write(opts['json'], {'track': track, 'model': opts['model'], 'stopped': stopped, 'results': results})
        self.stdout.write(f'{track}: {passed}/{len(results)} pass' + (f' — stopped: {stopped}' if stopped else ''))
