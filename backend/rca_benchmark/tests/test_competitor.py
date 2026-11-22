"""The competitor adapter: same evidence, same scoring, no model grading."""
import json
import os
from types import SimpleNamespace

from django.test import SimpleTestCase

from rca_benchmark import competitor
from rca_benchmark.held_out_v2 import SCENARIOS, v01_deadlock


class EvidenceTest(SimpleTestCase):

    def test_every_source_the_scenario_holds_is_given(self):
        for build in SCENARIOS:
            sc = build()
            files = competitor.evidence_files(sc['data'])
            expected = {'logs.txt' if k == 'logs' else 'changes.txt' if k == 'code_changes' else f'{k}.json'
                        for k in sc['data']}
            self.assertEqual(set(files), expected, sc['id'])

    def test_logs_and_diffs_are_readable_and_complete(self):
        data = v01_deadlock()['data']
        files = competitor.evidence_files(data)
        for record in data['logs']:            # messages may span several lines
            self.assertIn(record['_source']['message'], files['logs.txt'])
        self.assertIn('deadlock detected', files['logs.txt'])
        self.assertIn('wallet-api', files['logs.txt'])
        self.assertIn('commit a17c3e90', files['changes.txt'])
        self.assertIn('-        first, second = sorted([src_id, dst_id])', files['changes.txt'])
        self.assertEqual(json.loads(files['metrics_summary.json']), data['metrics_summary'])

    def test_the_answer_key_is_never_in_the_evidence(self):
        sc = v01_deadlock()
        text = ''.join(competitor.evidence_files(sc['data']).values())
        self.assertNotIn('blame_sha', text)
        self.assertNotIn('wrong_shas', text)


class ParseTest(SimpleTestCase):

    def test_plain_and_fenced_json(self):
        body = {'issues': [{'severity': 'critical', 'confidence': 'High', 'component': 'wallet-api',
                            'affected_services': ['wallet-api', 'postgres'], 'root_cause': 'lock order',
                            'description': 'deadlock', 'linked_commits': ['a17c3e90']}]}
        for text in (json.dumps(body), 'Here it is:\n```json\n' + json.dumps(body) + '\n```'):
            [issue] = competitor.parse_issues(text)
            self.assertEqual(issue['severity'], 'CRITICAL')
            self.assertEqual(issue['confidence'], 'HIGH')
            self.assertEqual(issue['linked_commits'], 'a17c3e90')

    def test_unreadable_answers_are_errors_not_quiet(self):
        for text in ('', 'The database deadlocked.', '{"result": 1}', '{"issues": "none"}'):
            with self.assertRaises(competitor.AnswerError):
                competitor.parse_issues(text)

    def test_an_empty_issue_list_is_a_quiet_answer(self):
        self.assertEqual(competitor.parse_issues('{"issues": []}'), [])

    def test_cost_uses_serops_prices(self):
        # The probe run on v01: HolmesGPT reported $0.034993 for these counts.
        usage = {'prompt_tokens': 11182, 'cache_creation_tokens': 11178, 'cached_tokens': 0,
                 'completion_tokens': 704}
        self.assertEqual(competitor.cost_usd(usage), 0.034993)


def _fake_holmes(result_text, returncode=0, usage=None):
    def runner(cmd, **kwargs):
        out = cmd[cmd.index('-v', cmd.index('-v') + 1) + 1].split(':')[0]
        if returncode == 0:
            with open(os.path.join(out, 'out.json'), 'w') as f:
                json.dump({'result': result_text, 'tool_calls': [], **(usage or {
                    'prompt_tokens': 1000, 'completion_tokens': 100})}, f)
        return SimpleNamespace(returncode=returncode, stdout='', stderr='boom' if returncode else '')
    return runner


class RunTest(SimpleTestCase):

    def test_command_is_pinned_and_non_interactive_with_every_file(self):
        files = competitor.evidence_files(v01_deadlock()['data'])
        cmd = competitor.holmes_command('/ev', '/out', '/k.env', files)
        self.assertIn('serops-bench/holmesgpt:0.46.0', cmd)
        self.assertIn('--no-interactive', cmd)
        self.assertIn('anthropic/claude-sonnet-5-5', cmd)
        self.assertEqual(sorted(cmd[i + 1] for i, a in enumerate(cmd) if a == '-f'),
                         sorted(f'/ev/{n}' for n in files))
        self.assertEqual(cmd[-1], competitor.QUESTION)

    def test_a_right_answer_scores_with_the_unchanged_rules(self):
        answer = json.dumps({'issues': [{'severity': 'CRITICAL', 'confidence': 'HIGH', 'component': 'wallet-api',
                                         'affected_services': ['wallet-api'], 'linked_commits': 'a17c3e90',
                                         'root_cause': 'commit a17c3e90 removed the sorted lock order: deadlock',
                                         'description': 'deadlock detected on transfers'}]})
        results, _ = competitor.run([v01_deadlock], '/k.env', analyse=lambda d: competitor.run_holmes(
            d, '/k.env', runner=_fake_holmes(answer)))
        self.assertTrue(results[0]['score']['root_cause'])
        self.assertEqual(results[0]['cost_usd'], 0.003)

    def test_a_failed_run_is_an_error_not_a_miss_or_a_pass(self):
        results, _ = competitor.run([v01_deadlock], '/k.env', analyse=lambda d: competitor.run_holmes(
            d, '/k.env', runner=_fake_holmes('', returncode=1)))
        self.assertIsNone(results[0]['score'])
        self.assertIn('holmes exited 1', results[0]['error'])

    def test_the_budget_stops_the_run(self):
        fake = lambda d: ([], None, 1.0, 0.6, 10, 10, [])   # noqa: E731
        results, stopped = competitor.run(SCENARIOS[:5], '/k.env', budget_usd=1.0, analyse=fake)
        self.assertEqual(len(results), 2)
        self.assertIn('budget reached', stopped)

    def test_dry_run_calls_nothing(self):
        called = []
        issues, error, *_ = competitor.run_holmes(v01_deadlock()['data'], '/k.env', dry_run=True,
                                                  runner=lambda *a, **k: called.append(a))
        self.assertEqual(called, [])
        self.assertIn('dry run', error)


class ModeTest(SimpleTestCase):

    def test_published_runs_use_holmesgpt_defaults_with_no_config_of_ours(self):
        files = competitor.evidence_files(v01_deadlock()['data'])
        default = competitor.holmes_command('/ev', '/out', '/k.env', files)
        self.assertNotIn('--config', default)
        self.assertFalse(any('holmes-config.yaml' in a for a in default))
        evidence_only = competitor.holmes_command('/ev', '/out', '/k.env', files, mode='evidence-only')
        self.assertIn('--config', evidence_only)

    def test_the_tools_it_called_are_recorded(self):
        answer = '{"issues": []}'
        usage = {'prompt_tokens': 10, 'completion_tokens': 1}

        def runner(cmd, **kwargs):
            out = cmd[cmd.index('-v', cmd.index('-v') + 1) + 1].split(':')[0]
            with open(os.path.join(out, 'out.json'), 'w') as f:
                json.dump({'result': answer, 'tool_calls': [{'tool_name': 'fetch_webpage'}, {'tool_name': 'kubectl_get'}],
                           **usage}, f)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        *_, tools = competitor.run_holmes(v01_deadlock()['data'], '/k.env', runner=runner)
        self.assertEqual(tools, ['fetch_webpage', 'kubectl_get'])


class RefusedTest(SimpleTestCase):

    def test_an_account_refusal_stops_the_run(self):
        fake = lambda d: ([], 'holmes exited 1: reached your specified API usage limits', 1.0, 0.0, 0, 0, [])  # noqa: E731
        results, stopped = competitor.run(SCENARIOS[:5], '/k.env', analyse=fake)
        self.assertEqual(len(results), 1)
        self.assertIn('refused the account', stopped)
