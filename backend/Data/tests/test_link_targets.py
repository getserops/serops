"""
A reference the pages link to says whether there is something to open:
``trace_stored`` on span items, ``in_batch`` on linked commits
(Data/link_targets.py).
"""

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.link_targets import commit_in_batch
from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence
from Organisations.models import Organisations
from Projects.models import Project
from traces.models import Trace
from Users.models import User

STORED, MISSING = 'a' * 32, 'b' * 32


class LinkTargetsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Link Org')
        cls.other_org = Organisations.objects.create(name='Other Org')
        cls.user = User.objects.create(email='links@acme.example', role='admin', is_active=True,
                                       organisation=cls.org)
        cls.project = Project.objects.create(name='shop', organisation=cls.org)
        now = timezone.now()
        spans = [
            {'trace_id': STORED, 'service_name': 'web', 'operation_name': 'GET /', 'duration_ms': 5,
             'status_message': 'boom', 'start_time': now.isoformat()},
            {'trace_id': MISSING, 'service_name': 'web', 'operation_name': 'GET /cart', 'duration_ms': 7,
             'status_message': 'boom', 'start_time': now.isoformat()},
        ]
        cls.batch = AIAnalyzedBatch.objects.create(
            batch_id='shop-batch-links', organisation=cls.org, project=cls.project, timestamp=now,
            environment='production',
            data={'traces': {'span_count': 2, 'error_span_count': 2, 'trace_count': 2,
                             'top_errors': spans, 'top_slow': spans[:1]},
                  'code_changes': [{'sha': '4d5abd995fa31a6467289e0b660f8be45341aac7', 'message': 'cap memory'}]},
        )
        cls.issue = Issue.objects.create(
            batch=cls.batch, project=cls.project, organisation=cls.org, severity='CRITICAL',
            description='web fails', issue_type='API_ERROR', component='web', environment='production',
            fingerprint='links-1', correlation_details={'engine': True},
        )
        Issue.objects.filter(pk=cls.issue.pk).update(
            has_commit_correlation=True,
            linked_commits=[{'sha': '4d5abd99', 'provider': 'unknown', 'project_id': None},
                            {'sha': '5ef5c6da', 'provider': 'unknown', 'project_id': None}])
        IssueOccurrence.objects.create(issue=cls.issue, batch=cls.batch, severity='CRITICAL')
        Trace.objects.create(trace_id=STORED, organisation=cls.org, start_time=now, end_time=now)
        # Another organisation's trace with the missing id does not count.
        Trace.objects.create(trace_id=MISSING, organisation=cls.other_org, start_time=now, end_time=now)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_batch_detail_flags_each_span(self):
        detail = self.client.get(f'/api/data/batches/{self.batch.batch_id}/').json()
        flags = {s['trace_id']: s['trace_stored'] for s in detail['data']['traces']['top_errors']}
        self.assertEqual(flags, {STORED: True, MISSING: False})
        self.assertEqual([s['trace_stored'] for s in detail['data']['traces']['top_slow']], [True])
        related = detail['issues'][0]['related_traces']
        self.assertEqual({s['trace_id']: s['trace_stored'] for s in related['top_errors']},
                         {STORED: True, MISSING: False})

    def test_the_stored_snapshot_is_not_changed(self):
        self.client.get(f'/api/data/batches/{self.batch.batch_id}/')
        self.client.get('/api/data/issues/')
        self.batch.refresh_from_db()
        for span in self.batch.data['traces']['top_errors']:
            self.assertNotIn('trace_stored', span)
        self.issue.refresh_from_db()
        self.assertNotIn('in_batch', self.issue.linked_commits[0])

    def test_timeline_flags_span_events(self):
        events = self.client.get(f'/api/data/batches/{self.batch.batch_id}/timeline/').json()['events']
        flags = {e['detail']['trace_id']: e['detail']['trace_stored']
                 for e in events if e['kind'] == 'span_error'}
        self.assertEqual(flags, {STORED: True, MISSING: False})
        # Events that name no trace get no flag.
        self.assertTrue(all('trace_stored' not in e['detail'] for e in events if e['kind'] != 'span_error'))

    def test_linked_commits_say_whether_the_batch_holds_them(self):
        row = self.client.get('/api/data/issues/').json()['results'][0]
        self.assertEqual([(c['sha'], c['in_batch']) for c in row['linked_commits']],
                         [('4d5abd99', True), ('5ef5c6da', False)])
        commit = next(e for e in row['correlation_summary'] if e['type'] == 'commit')
        self.assertEqual((commit['value'], commit['in_batch']), ('4d5abd99', True))

    def test_a_batch_without_snapshot_or_code_changes(self):
        bare = AIAnalyzedBatch.objects.create(
            batch_id='shop-batch-bare', organisation=self.org, project=self.project,
            timestamp=timezone.now(), environment='production', data={})
        detail = self.client.get(f'/api/data/batches/{bare.batch_id}/').json()
        self.assertEqual(detail['data'], {})

    def test_short_and_full_shas_match(self):
        self.assertTrue(commit_in_batch('4D5ABD99', ['4d5abd995fa3']))
        self.assertTrue(commit_in_batch('4d5abd995fa31a64', ['4d5abd99']))
        self.assertFalse(commit_in_batch('5ef5c6da', ['4d5abd99']))
        self.assertFalse(commit_in_batch('', ['4d5abd99']))
        self.assertFalse(commit_in_batch('4d5abd99', []))
