"""
An ongoing critical incident is re-reported by every batch. The on-call
``critical_issue`` event used to fire for each one, so the on-call engineer got
the same email every 5 minutes. It now fires when an issue becomes critical:
new, escalated, or back after an hour without a critical sighting.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence
from Organisations.models import Organisations
from Projects.models import Project


class CriticalRepageTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Page Org')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.n = 0
        self.first = self.batch()
        self.issue = Issue.objects.create(
            batch=self.first, project=self.project, organisation=self.org, severity='CRITICAL',
            component='payments', description='payments down', fingerprint='fp-page')

    def batch(self):
        self.n += 1
        return AIAnalyzedBatch.objects.create(
            batch_id=f'b-page-{self.n}', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={})

    def seen(self, batch, severity, ago=None):
        occ = IssueOccurrence.objects.create(issue=self.issue, batch=batch, severity=severity)
        if ago is not None:
            IssueOccurrence.objects.filter(pk=occ.pk).update(seen_at=timezone.now() - ago)
        return batch

    def test_a_new_critical_issue_pages(self):
        self.assertTrue(self.issue.is_newly_critical(self.seen(self.first, 'CRITICAL')))

    def test_the_next_batch_of_the_same_incident_does_not(self):
        self.seen(self.first, 'CRITICAL', ago=timedelta(minutes=5))
        self.assertFalse(self.issue.is_newly_critical(self.seen(self.batch(), 'CRITICAL')))

    def test_escalating_to_critical_pages(self):
        self.seen(self.first, 'WARNING', ago=timedelta(minutes=5))
        self.assertTrue(self.issue.is_newly_critical(self.seen(self.batch(), 'CRITICAL')))

    def test_back_after_an_hour_pages_again(self):
        self.seen(self.first, 'CRITICAL', ago=timedelta(hours=2))
        self.assertTrue(self.issue.is_newly_critical(self.seen(self.batch(), 'CRITICAL')))

    def test_a_warning_never_pages(self):
        self.assertFalse(self.issue.is_newly_critical(self.seen(self.first, 'WARNING')))
