"""Tests for IssueSerializer.related_traces (Item #12a)."""

from django.test import TestCase

from Data.models import AIAnalyzedBatch, Issue
from Data.serializers import IssueSerializer
from Organisations.models import Organisations


def _make_batch(org, traces_snapshot):
    return AIAnalyzedBatch.objects.create(
        batch_id='b_traces',
        organisation=org,
        data={'traces': traces_snapshot} if traces_snapshot is not None else {},
    )


def _make_issue(batch, component='checkout'):
    return Issue.objects.create(
        batch=batch,
        organisation=batch.organisation,
        severity='high',
        description='boom',
        component=component,
        issue_type='error',
        fingerprint=f'fp-{component}',
    )


class RelatedTracesTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='RelatedTracesOrg')

    def _serialize(self, issue):
        return IssueSerializer(issue).data['related_traces']

    def test_no_batch_data_returns_empty(self):
        batch = AIAnalyzedBatch.objects.create(batch_id='b1', organisation=self.org)
        # data is defaulted to {} — no 'traces' key.
        issue = _make_issue(batch)
        data = self._serialize(issue)
        self.assertEqual(data['trace_count'], 0)
        self.assertEqual(data['top_slow'], [])

    def test_snapshot_absent_returns_empty(self):
        batch = _make_batch(self.org, {})   # empty snapshot
        issue = _make_issue(batch)
        self.assertEqual(self._serialize(issue)['trace_count'], 0)

    def test_snapshot_populated_returns_summary(self):
        snapshot = {
            'trace_count': 3, 'span_count': 12, 'error_span_count': 2,
            'top_slow': [
                {'trace_id': 'a' * 32, 'service_name': 'checkout',
                  'operation_name': 'POST /checkout', 'duration_ms': 1200},
                {'trace_id': 'b' * 32, 'service_name': 'api',
                  'operation_name': 'GET /users', 'duration_ms': 300},
            ],
            'top_errors': [
                {'trace_id': 'c' * 32, 'service_name': 'checkout',
                  'operation_name': 'POST /checkout', 'status_message': 'timeout'},
            ],
        }
        batch = _make_batch(self.org, snapshot)
        issue = _make_issue(batch, component='checkout')
        data = self._serialize(issue)
        self.assertEqual(data['trace_count'], 3)
        self.assertEqual(data['span_count'], 12)
        self.assertEqual(data['error_span_count'], 2)
        # top_slow filtered to the issue's service (checkout) — api is dropped.
        self.assertEqual(len(data['top_slow']), 1)
        self.assertEqual(data['top_slow'][0]['service_name'], 'checkout')

    def test_service_filter_falls_back_to_all(self):
        """When no span matches the issue's service, we return the top-N
        overall — better than showing nothing."""
        snapshot = {
            'trace_count': 1, 'span_count': 3, 'error_span_count': 0,
            'top_slow': [
                {'trace_id': 'x' * 32, 'service_name': 'api',
                  'operation_name': 'GET /users', 'duration_ms': 500},
            ],
            'top_errors': [],
        }
        batch = _make_batch(self.org, snapshot)
        issue = _make_issue(batch, component='checkout')   # no api match
        data = self._serialize(issue)
        # Falls back — the caller still learns something.
        self.assertEqual(len(data['top_slow']), 1)
        self.assertEqual(data['top_slow'][0]['service_name'], 'api')

    def test_no_component_returns_full_top_n(self):
        snapshot = {
            'trace_count': 1, 'span_count': 5, 'error_span_count': 1,
            'top_slow': [
                {'trace_id': 'a' * 32, 'service_name': 'checkout',
                  'operation_name': 'POST /', 'duration_ms': 500},
                {'trace_id': 'b' * 32, 'service_name': 'api',
                  'operation_name': 'GET /', 'duration_ms': 300},
            ],
            'top_errors': [],
        }
        batch = _make_batch(self.org, snapshot)
        issue = _make_issue(batch, component='')   # no service label
        data = self._serialize(issue)
        self.assertEqual(len(data['top_slow']), 2)
