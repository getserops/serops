"""
Two things the RCA benchmark showed (2026-10-28):

- h04: the prompt never said which host a log came from, so clock skew
  on one node read like a service-wide failure.
- h07: an issue linked every commit its root cause named, including one
  the AI named only to clear it.
"""
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from ai_model.tasks import _hosts_note, _prompt_log_line


def _source(message, level, component, host=None):
    doc = {'message': message, 'level': level.upper(), 'service': component}  # as the batch task stores logs
    if host:
        doc['host'] = host
    return {'_source': doc}


class PromptLogLineTest(SimpleTestCase):
    def test_the_host_follows_the_service(self):
        self.assertEqual(
            _prompt_log_line({'timestamp': 't', 'level': 'ERROR', 'component': 'auth-gateway',
                              'host': 'node-c', 'message': 'JWT rejected'}),
            '[t] [ERROR] [auth-gateway] [node-c] JWT rejected')

    def test_an_unknown_host_is_left_out(self):
        for host in ('', 'unknown', None):
            self.assertEqual(
                _prompt_log_line({'timestamp': 't', 'level': 'ERROR', 'component': 'api',
                                  'host': host, 'message': 'boom'}),
                '[t] [ERROR] [api] boom')

    def test_hosts_of_a_repeated_line(self):
        self.assertEqual(_hosts_note({'node-c': 8}), ' on node-c')
        self.assertEqual(_hosts_note({'node-a': 1, 'node-c': 5, '': 2}), ' on 2 hosts: node-c (5), node-a (1)')
        self.assertEqual(_hosts_note({'': 3, 'unknown': 1}), '')


class HostsReachThePromptTest(TestCase):
    def analyse(self, logs):
        from ai_model.tasks import analyze_batch
        from Data.models import AIAnalyzedBatch
        from Organisations.models import Organisations
        from Projects.models import Project

        org = Organisations.objects.create(name='Hosts org')
        AIAnalyzedBatch.objects.create(
            batch_id='hosts-reach-prompt', organisation=org, environment='production',
            project=Project.objects.create(name='p', organisation=org),
            data={'logs': logs, 'metrics': {}, 'metrics_summary': {}, 'code_changes': [], 'cicd_logs': [],
                  'statistics': {'total_logs': len(logs), 'total_metrics': 0, 'total_code_changes': 0,
                                 'total_cicd_logs': 0}})
        with patch('ai_model.tasks.generate_for_organisation') as generate:
            generate.return_value = (json.dumps({'summary': {'overall_health': 'HEALTHY'},
                                                 'correlated_issues': [], 'recommendations': []}),
                                     'gemini', None, 10, 5)
            analyze_batch('hosts-reach-prompt')
        return generate.call_args.args[0]

    def test_a_few_logs_carry_their_host(self):
        prompt = self.analyse([
            _source('JWT rejected: token used before issued', 'error', 'auth-gateway', 'node-c'),
            _source('System clock wrong by -94.018 seconds', 'warn', 'chronyd', 'node-c'),
        ])
        self.assertIn('[auth-gateway] [node-c] JWT rejected', prompt)
        self.assertIn('[chronyd] [node-c] System clock wrong', prompt)

    def test_a_repeated_line_says_it_came_from_one_host(self):
        logs = [_source(f'JWT rejected: token used before issued (attempt {i})', 'error', 'auth-gateway', 'node-c')
                for i in range(25)]
        prompt = self.analyse(logs)
        self.assertRegex(prompt, r'JWT rejected.*Repeated 25 times between .* on node-c\]')


class CausedByCommitsTest(TestCase):
    def make(self, root_cause, **extra):
        from Data.models import AIAnalyzedBatch, Issue
        from Organisations.models import Organisations
        from Projects.models import Project

        org = Organisations.objects.create(name=f'Commit org {Issue.objects.count()}')
        project = Project.objects.create(name='tax', organisation=org)
        batch = AIAnalyzedBatch.objects.create(batch_id=f'b-{Issue.objects.count()}', organisation=org,
                                               project=project, environment='production', data={})
        data = {'issue_type': 'API_ERROR', 'scope': 'SERVICE', 'component': 'tax-svc', 'severity': 'WARNING',
                'description': 'd', 'root_cause': root_cause, 'error_class': 'OTHER', 'error_target': 'x', **extra}
        issue, _ = Issue.find_or_create_deduplicated(data, batch, project, 'production')
        issue.refresh_from_db()
        return issue

    CLEARED = ('The v2 tax engine has no rule for CA-QC. Commit 8a9b0c1d (test(tax): more fixtures) '
               'only added a US-NY test fixture and did not cause it.')

    def test_a_commit_named_to_clear_it_is_not_linked(self):
        issue = self.make(self.CLEARED, caused_by_commits=[])
        self.assertEqual(issue.linked_commits, [])
        self.assertFalse(issue.has_commit_correlation)

    def test_the_commit_at_fault_is_linked(self):
        issue = self.make('Commit 4b0e77d1 leaks a session; commit 9c1d2e3f is unrelated.',
                          caused_by_commits=['4B0E77D1', '`4b0e77d1`', 'not-a-sha'])
        self.assertEqual([c['sha'] for c in issue.linked_commits], ['4b0e77d1'])
        self.assertTrue(issue.has_commit_correlation)

    def test_an_answer_without_the_field_keeps_the_text_scan(self):
        issue = self.make(self.CLEARED)
        self.assertEqual([c['sha'] for c in issue.linked_commits], ['8a9b0c1d'])

    def test_the_schema_asks_for_it(self):
        from ai_model.prompts import get_batch_analysis_system_prompt
        prompt = get_batch_analysis_system_prompt()
        self.assertIn('"caused_by_commits"', prompt)
        self.assertIn('rule it out', prompt)
        self.assertIn('[service] [host] message', prompt, 'the log line format is explained')
