"""
During an incident, a finding from reviewing the code is a note, not a
suspect (RCA benchmark h01/h04, Claude: a second WARNING blamed an innocent
commit for an unused import).
"""
import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from ai_model.tasks import _demote_side_code_findings

INCIDENT = {'scope': 'SERVICE', 'severity': 'CRITICAL', 'component': 'auth-gateway', 'issue_type': 'AUTH_FAILURE',
            'description': 'JWT rejected on node-c', 'root_cause': 'chronyd on node-c: clock off by -94 s',
            'error_class': 'TOKEN_EXPIRED', 'error_target': 'iat', 'evidence_sources': {'logs': ['JWT rejected']},
            'caused_by_commits': []}
UNUSED_IMPORT = {'scope': 'CODE', 'severity': 'WARNING', 'component': 'auth-gateway', 'issue_type': 'POTENTIAL_BUG',
                 'description': 'Unused import breaks the build',
                 'root_cause': 'Commit 2aa7d19c adds import "log/slog" in gateway/auth/logging.go with no use.',
                 'error_class': 'BUILD_COMPILE', 'error_target': 'log/slog', 'caused_by_commits': ['2aa7d19c']}


class DemoteTest(SimpleTestCase):
    def test_during_an_incident_a_code_finding_becomes_a_note(self):
        result = {'correlated_issues': [dict(INCIDENT), dict(UNUSED_IMPORT)]}
        self.assertEqual(_demote_side_code_findings(result), 1)
        note = result['correlated_issues'][1]
        self.assertEqual((note['severity'], note['caused_by_commits']), ('INFO', []))
        self.assertEqual(result['correlated_issues'][0]['severity'], 'CRITICAL')

    def test_without_an_incident_code_review_keeps_its_severity(self):
        result = {'correlated_issues': [dict(UNUSED_IMPORT)]}
        self.assertEqual(_demote_side_code_findings(result), 0)
        self.assertEqual(result['correlated_issues'][0]['severity'], 'WARNING')

    def test_a_code_issue_citing_runtime_evidence_is_kept(self):
        cause = dict(UNUSED_IMPORT, severity='CRITICAL', evidence_sources={'logs': ['QueuePool limit reached']})
        result = {'correlated_issues': [dict(INCIDENT), cause]}
        self.assertEqual(_demote_side_code_findings(result), 0)
        self.assertEqual(result['correlated_issues'][1]['severity'], 'CRITICAL')

    def test_an_info_runtime_issue_is_not_an_incident(self):
        quiet = dict(INCIDENT, severity='INFO')
        result = {'correlated_issues': [quiet, dict(UNUSED_IMPORT)]}
        self.assertEqual(_demote_side_code_findings(result), 0)

    def test_the_prompt_says_so(self):
        from ai_model.prompts import get_batch_analysis_system_prompt
        self.assertIn('is a note, not a suspect', get_batch_analysis_system_prompt())


class StoredIssuesTest(TestCase):
    def test_the_note_is_info_and_links_no_commit(self):
        from ai_model.tasks import analyze_batch
        from Data.models import AIAnalyzedBatch, Issue
        from Organisations.models import Organisations
        from Projects.models import Project

        org = Organisations.objects.create(name='Notes org')
        batch = AIAnalyzedBatch.objects.create(
            batch_id='code-notes', organisation=org, environment='production',
            project=Project.objects.create(name='auth', organisation=org),
            data={'logs': [{'_source': {'message': 'JWT rejected', 'level': 'ERROR', 'service': 'auth-gateway'}}],
                  'metrics': {}, 'metrics_summary': {}, 'code_changes': [], 'cicd_logs': [],
                  'statistics': {'total_logs': 1, 'total_metrics': 0, 'total_code_changes': 0, 'total_cicd_logs': 0}})
        with patch('ai_model.tasks.generate_for_organisation') as generate:
            generate.return_value = (json.dumps({'summary': {'overall_health': 'CRITICAL'},
                                                 'correlated_issues': [INCIDENT, UNUSED_IMPORT],
                                                 'recommendations': []}), 'claude', None, 10, 5)
            analyze_batch('code-notes')

        note = Issue.objects.get(scope='CODE')
        self.assertEqual(note.severity, 'INFO')
        self.assertEqual(note.linked_commits, [], 'the commit is named in the text, not linked as a suspect')
        self.assertIn('2aa7d19c', note.root_cause)
        self.assertEqual(Issue.objects.get(scope='SERVICE').severity, 'CRITICAL')

        from notifications.incident_dispatcher import _top_issues
        self.assertEqual([i['component'] for i in _top_issues(batch)], ['auth-gateway'])
        self.assertEqual(len(_top_issues(batch)), 1, 'the note is not in the incident summary')
