"""
One incident, one issue: an incident that changes type as it evolves (memory
leak -> pod crashes -> recovering) stays on the issue that first reported it,
instead of a new issue per step (held-out v3 w36-w40, every model, 2026-11-16).
Two different incidents are not merged: two causes in one batch, another
component, another environment, a resolved issue, or one gone quiet longer
than the continuity horizon.
"""
import os
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from Organisations.models import Organisations
from Projects.models import Project
from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence


def finding(issue_type, component='events-api', severity='WARNING', **extra):
    data = {
        'issue_type': issue_type,
        'scope': 'SERVICE',
        'component': component,
        'severity': severity,
        'description': f'{issue_type} on {component}',
        'root_cause': f'{issue_type} cause',
        'recommended_action': 'act',
        'error_class': issue_type,
        'error_target': component,
    }
    data.update(extra)
    return data


class IssueContinuityTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Continuity Org')
        self.project = Project.objects.create(name='events', organisation=self.org)
        self.n = 0

    def batch(self):
        self.n += 1
        return AIAnalyzedBatch.objects.create(
            batch_id=f'b-cont-{self.n}', project=self.project, organisation=self.org,
            timestamp=timezone.now(), data={}, environment='production')

    def add(self, data, batch=None, environment='production'):
        return Issue.find_or_create_deduplicated(data, batch or self.batch(), self.project, environment)

    def test_evolving_incident_stays_one_issue(self):
        leak, created = self.add(finding('MEMORY_LEAK', severity='WARNING'))
        self.assertTrue(created)
        crash, created = self.add(finding('POD_CRASH', severity='CRITICAL'))
        self.assertFalse(created)
        self.assertEqual(crash.pk, leak.pk)
        self.assertEqual(crash.issue_type, 'POD_CRASH')
        self.assertEqual(crash.severity, 'CRITICAL')
        self.assertEqual(crash.description, 'POD_CRASH on events-api')
        steady, _ = self.add(finding('SERVICE_RESTART', severity='INFO'))
        self.assertEqual(steady.pk, leak.pk)
        self.assertEqual(steady.severity, 'INFO')
        self.assertEqual(Issue.objects.filter(project=self.project).count(), 1)
        types = list(IssueOccurrence.objects.filter(issue=leak).order_by('seen_at', 'pk')
                     .values_list('issue_type', flat=True))
        self.assertEqual(types, ['MEMORY_LEAK', 'POD_CRASH', 'SERVICE_RESTART'])

    def test_next_sighting_of_the_new_type_matches_directly(self):
        first, _ = self.add(finding('MEMORY_LEAK'))
        self.add(finding('POD_CRASH', severity='CRITICAL'))
        again, created = self.add(finding('POD_CRASH', severity='CRITICAL'))
        self.assertFalse(created)
        self.assertEqual(again.pk, first.pk)

    def test_two_causes_in_one_batch_stay_two_issues(self):
        batch = self.batch()
        a, _ = self.add(finding('DATABASE_ERROR', component='orders-api', severity='CRITICAL'), batch)
        b, created = self.add(finding('DISK_FULL', component='orders-api', severity='WARNING'), batch)
        self.assertTrue(created)
        self.assertNotEqual(a.pk, b.pk)

    def test_other_component_is_not_merged(self):
        lam, _ = self.add(finding('CONNECTION_TIMEOUT', component='order-intake'))
        db, created = self.add(finding('DATABASE_ERROR', component='inventory-api'))
        self.assertTrue(created)
        self.assertNotEqual(lam.pk, db.pk)

    def test_other_environment_is_not_merged(self):
        prod, _ = self.add(finding('MEMORY_LEAK'))
        stg, created = self.add(finding('POD_CRASH'), environment='staging')
        self.assertTrue(created)
        self.assertNotEqual(prod.pk, stg.pk)

    def test_resolved_issue_is_not_continued(self):
        old, _ = self.add(finding('MEMORY_LEAK'))
        Issue.objects.filter(pk=old.pk).update(status='RESOLVED')
        new, created = self.add(finding('POD_CRASH'))
        self.assertTrue(created)
        self.assertNotEqual(new.pk, old.pk)

    def test_quiet_longer_than_horizon_is_a_new_incident(self):
        old, _ = self.add(finding('MEMORY_LEAK'))
        Issue.objects.filter(pk=old.pk).update(last_seen_at=timezone.now() - timedelta(hours=3))
        new, created = self.add(finding('POD_CRASH'))
        self.assertTrue(created)
        self.assertNotEqual(new.pk, old.pk)

    def test_horizon_zero_turns_it_off(self):
        old, _ = self.add(finding('MEMORY_LEAK'))
        with mock.patch.dict(os.environ, {'SEROPS_ISSUE_CONTINUITY_HOURS': '0'}):
            new, created = self.add(finding('POD_CRASH'))
        self.assertTrue(created)
        self.assertNotEqual(new.pk, old.pk)

    def test_recovery_step_keeps_the_culprit_commit(self):
        first, _ = self.add(finding('MEMORY_LEAK', caused_by_commits=['a17c3e90']))
        self.assertTrue(first.has_commit_correlation)
        later, _ = self.add(finding('SERVICE_RESTART', severity='INFO', caused_by_commits=[]))
        self.assertEqual(later.pk, first.pk)
        self.assertTrue(later.has_commit_correlation)
