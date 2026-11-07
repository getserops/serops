"""
An analysis shows each issue at the severity IT reported. An issue's own
severity only ever escalates across recurrences, so an issue once CRITICAL
headlined every later analysis as CRITICAL, even one that rated it WARNING
(Online Boutique R7: a stuck rollout capped at WARNING still showed CRITICAL).
"""

from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence
from Data.serializers import AIAnalyzedBatchSerializer
from Organisations.models import Organisations
from Projects.models import Project
from Users.models import User


class BatchSeverityTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='Severity Org')
        project = Project.objects.create(name='boutique', organisation=org)
        self.user = User.objects.create_user(username='sev', email='sev@example.com', password='TestPass123!',
                                             organisation=org, role='admin', is_active=True)
        make = lambda bid: AIAnalyzedBatch.objects.create(
            batch_id=bid, project=project, organisation=org, timestamp=timezone.now(), data={})
        self.earlier, self.later = make('b-earlier'), make('b-later')
        base = dict(project=project, organisation=org, environment='production',
                    issue_type='OTHER', root_cause='x', recommendation='y')
        # Rated CRITICAL by the earlier analysis, WARNING by the later one.
        self.stuck = Issue.objects.create(**base, batch=self.later, severity='CRITICAL', component='currencyservice',
                                          description='rollout stuck', fingerprint='fp-stuck')
        IssueOccurrence.objects.create(issue=self.stuck, batch=self.earlier, severity='CRITICAL')
        IssueOccurrence.objects.create(issue=self.stuck, batch=self.later, severity='WARNING')
        self.redis = Issue.objects.create(**base, batch=self.later, severity='CRITICAL', component='redis-cart',
                                          description='redis full', fingerprint='fp-redis')
        IssueOccurrence.objects.create(issue=self.redis, batch=self.later, severity='CRITICAL')

    def test_the_analysis_page_shows_the_severity_this_analysis_reported(self):
        issues = AIAnalyzedBatchSerializer(self.later).data['issues']
        self.assertEqual([(i['component'], i['severity']) for i in issues],
                         [('redis-cart', 'CRITICAL'), ('currencyservice', 'WARNING')])
        self.stuck.refresh_from_db()
        self.assertEqual(self.stuck.severity, 'CRITICAL')  # the issue itself keeps its peak

    def test_the_batch_issue_list_filters_sorts_and_counts_by_it(self):
        self.client.force_authenticate(user=self.user)
        body = self.client.get('/api/data/issues/b-later/').json()
        self.assertEqual([(i['component'], i['severity']) for i in body['results']],
                         [('redis-cart', 'CRITICAL'), ('currencyservice', 'WARNING')])
        self.assertEqual(body['summary']['severity_distribution'], {'CRITICAL': 1, 'WARNING': 1})
        warnings = self.client.get('/api/data/issues/b-later/?severity=WARNING').json()['results']
        self.assertEqual([i['component'] for i in warnings], ['currencyservice'])

    def test_an_occurrence_without_a_severity_falls_back_to_the_issue(self):
        IssueOccurrence.objects.filter(batch=self.later, issue=self.stuck).update(severity=None)
        self.client.force_authenticate(user=self.user)
        body = self.client.get('/api/data/issues/b-later/?severity=CRITICAL').json()
        self.assertEqual(sorted(i['component'] for i in body['results']), ['currencyservice', 'redis-cart'])
