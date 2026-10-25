"""
The analysis page headlines issues[0] as the root cause, so the batch API must
list the root cause first: most severe, then most confident, then the AI's own
order (creation order). Issue's default ordering is newest first, which used to
put the AI's last issue (a minor symptom) in the headline.
"""

from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch, Issue
from Data.serializers import AIAnalyzedBatchSerializer
from Organisations.models import Organisations
from Projects.models import Project


class BatchIssueOrderTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='Order Org')
        project = Project.objects.create(name='shop', organisation=org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='b-order', project=project, organisation=org, timestamp=timezone.now(), data={})
        self.base = dict(batch=self.batch, project=project, organisation=org, environment='production',
                         issue_type='OTHER', root_cause='x', recommendation='y')

    def issue(self, n, component, severity, confidence='MEDIUM'):
        return Issue.objects.create(**self.base, severity=severity, confidence=confidence,
                                    component=component, description=f'{component} {n}', fingerprint=f'fp-{n}')

    def components(self):
        return [i['component'] for i in AIAnalyzedBatchSerializer(self.batch).data['issues']]

    def test_root_cause_first_in_ai_order(self):
        """AI answer: payments (root, CRITICAL) then two symptoms, created in that order."""
        self.issue(1, 'payments', 'CRITICAL', 'HIGH')
        self.issue(2, 'checkout', 'WARNING')
        self.issue(3, 'frontend', 'WARNING')
        self.assertEqual(self.components(), ['payments', 'checkout', 'frontend'])

    def test_severity_beats_creation_order(self):
        self.issue(1, 'checkout', 'WARNING')
        self.issue(2, 'payments', 'CRITICAL')
        self.assertEqual(self.components()[0], 'payments')

    def test_confidence_breaks_severity_ties(self):
        self.issue(1, 'checkout', 'CRITICAL', 'LOW')
        self.issue(2, 'payments', 'CRITICAL', 'HIGH')
        self.assertEqual(self.components()[0], 'payments')
