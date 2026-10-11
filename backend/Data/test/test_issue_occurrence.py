"""Batch history must survive an issue recurring.

``Issue.batch`` is a single FK holding the MOST RECENT sighting, and the old
``move_to_batch`` repointed it on every recurrence while decrementing the
previous batch's ``issue_count``. The consequence was that a batch's issue list
shrank over time and could empty entirely: the batch detail page answered
"which issues are still most recently seen here?" while appearing to answer
"what did this analysis find?".

Measured on the chaos-RCA run before the fix: of 25 analysed batches, 17 listed
fewer issues than their own stored analysis had reported, and two listed none
at all despite having reported one.
"""
import uuid

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch, Issue, IssueOccurrence


def _batch(suffix):
    return AIAnalyzedBatch.objects.create(
        batch_id=f'occ_batch_{suffix}', timestamp=timezone.now(),
    )


def _issue_data(component='cache', issue_type='MEMORY_HIGH', severity='CRITICAL'):
    return {
        'issue_type': issue_type,
        'scope': 'SERVICE',
        'component': component,
        'severity': severity,
        'description': f'{component} is unhappy',
        'root_cause': 'because of reasons',
    }


class RecurrenceKeepsBatchHistoryTest(TestCase):
    def setUp(self):
        self.b1 = _batch('one')
        self.b2 = _batch('two')

    def _report(self, batch, **kw):
        issue, created = Issue.find_or_create_deduplicated(
            issue_data=_issue_data(**kw), batch=batch, project=None,
            environment='production',
        )
        return issue, created

    def test_first_sighting_records_an_occurrence(self):
        issue, created = self._report(self.b1)
        self.assertTrue(created)
        self.assertEqual(
            IssueOccurrence.objects.filter(issue=issue, batch=self.b1).count(), 1)

    def test_recurrence_does_not_erase_the_first_batch(self):
        """The whole point: batch one must still own its finding."""
        issue, _ = self._report(self.b1)
        again, created = self._report(self.b2)
        self.assertFalse(created, 'same fingerprint should dedupe')
        self.assertEqual(again.pk, issue.pk)

        self.assertTrue(
            Issue.objects.filter(occurrences__batch=self.b1).exists(),
            'batch one lost the issue it found')
        self.assertTrue(
            Issue.objects.filter(occurrences__batch=self.b2).exists())

    def test_latest_pointer_still_follows_the_newest_sighting(self):
        issue, _ = self._report(self.b1)
        self._report(self.b2)
        issue.refresh_from_db()
        self.assertEqual(issue.batch_id, self.b2.id,
                         'Issue.batch should still mean "last seen here"')

    def test_occurrence_count_grows_with_sightings(self):
        issue, _ = self._report(self.b1)
        self._report(self.b2)
        self.assertEqual(IssueOccurrence.objects.filter(issue=issue).count(), 2)

    def test_same_batch_reporting_twice_is_one_occurrence(self):
        """A duplicate within one analysis is not two sightings."""
        issue, _ = self._report(self.b1)
        self._report(self.b1)
        self.assertEqual(
            IssueOccurrence.objects.filter(issue=issue, batch=self.b1).count(), 1)

    def test_a_batch_lists_every_issue_it_reported(self):
        self._report(self.b1, component='cache')
        self._report(self.b1, component='api', issue_type='API_ERROR')
        self._report(self.b1, component='checkout', issue_type='SERVICE_UNAVAILABLE')
        # A later batch re-reports two of them.
        self._report(self.b2, component='cache')
        self._report(self.b2, component='api', issue_type='API_ERROR')

        first = Issue.objects.filter(occurrences__batch=self.b1).distinct()
        self.assertEqual(first.count(), 3,
                         'batch one reported three issues and must still show three')
        second = Issue.objects.filter(occurrences__batch=self.b2).distinct()
        self.assertEqual(second.count(), 2)

    def test_severity_is_captured_per_sighting(self):
        """An issue upgraded to CRITICAL later must not rewrite what an earlier
        batch actually said."""
        self._report(self.b1, severity='WARNING')
        self._report(self.b2, severity='CRITICAL')
        first = IssueOccurrence.objects.get(batch=self.b1)
        self.assertEqual(first.severity, 'WARNING')

    def test_record_occurrence_tolerates_no_batch(self):
        issue, _ = self._report(self.b1)
        issue.record_occurrence(None)
        self.assertEqual(IssueOccurrence.objects.filter(issue=issue).count(), 1)


class BatchIssueCountTest(TestCase):
    """``issue_count`` must reflect what the batch reported, and stay put."""

    def setUp(self):
        self.b1 = _batch('count_one')
        self.b2 = _batch('count_two')

    def _report(self, batch, component):
        return Issue.find_or_create_deduplicated(
            issue_data=_issue_data(component=component), batch=batch,
            project=None, environment='production',
        )

    def test_counting_through_occurrences_is_stable_across_recurrence(self):
        self._report(self.b1, 'cache')
        self._report(self.b1, 'api')
        before = Issue.objects.filter(occurrences__batch=self.b1).distinct().count()

        self._report(self.b2, 'cache')

        after = Issue.objects.filter(occurrences__batch=self.b1).distinct().count()
        self.assertEqual(before, 2)
        self.assertEqual(after, 2, 'a later batch must not decrement an earlier one')
