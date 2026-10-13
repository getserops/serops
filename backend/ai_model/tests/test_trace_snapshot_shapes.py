"""PR-TRACE1 regression fence for ``ai_model.trace_context._read_snapshot``.

The trace-prompt path silently ignored ``batch.data['traces']`` if the
snapshot wasn't shaped like ``_from_native``'s dict (span_count,
top_slow, top_errors, etc). C4 (Tier 3 gauntlet) uncovered this by
writing a list; the AI never saw the trace and named "upstream
degraded" instead of the postgres root. Fix: fall through to live
query when the snapshot is the wrong type/shape.

These tests pin that behaviour so we don't silently regress.
"""
from __future__ import annotations
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project
from ai_model.trace_context import _read_snapshot


class TraceSnapshotShapeTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='ts-org')
        self.project = Project.objects.create(organisation=self.org, name='ts-project')

    def _make_batch(self, data):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'ts-{timezone.now().timestamp()}',
            project=self.project, organisation=self.org,
            timestamp=timezone.now(), data=data,
        )

    def test_missing_traces_returns_none(self):
        b = self._make_batch({'logs': []})
        self.assertIsNone(_read_snapshot(b))

    def test_none_traces_returns_none(self):
        b = self._make_batch({'traces': None})
        self.assertIsNone(_read_snapshot(b))

    def test_list_traces_falls_through(self):
        # Old ingest shape. Reader must NOT return a list — the
        # prompt formatter can't ``.get()`` on it and would render
        # nothing while eating the exception silently.
        b = self._make_batch({'traces': [
            {'trace_id': 'a' * 32, 'root_service': 'pg', 'duration_ms': 100},
        ]})
        self.assertIsNone(_read_snapshot(b))

    def test_dict_without_expected_keys_falls_through(self):
        b = self._make_batch({'traces': {'foo': 1, 'bar': 'baz'}})
        self.assertIsNone(_read_snapshot(b))

    def test_dict_with_expected_keys_returned_as_is(self):
        snapshot = {
            'source': 'otlp',
            'span_count': 12,
            'error_span_count': 3,
            'trace_count': 1,
            'top_slow': [{'trace_id': 'a' * 32, 'service_name': 'pg',
                          'operation_name': 'SELECT', 'duration_ms': 100,
                          'status_code': 'ERROR'}],
            'top_errors': [{'trace_id': 'a' * 32, 'service_name': 'pg',
                            'operation_name': 'SELECT',
                            'status_message': 'lock_wait_timeout',
                            'duration_ms': 100}],
            'services_touched': ['pg'],
        }
        b = self._make_batch({'traces': snapshot})
        got = _read_snapshot(b)
        self.assertEqual(got, snapshot)

    def test_partial_dict_only_span_count_returned(self):
        # Minimal valid shape — just span_count is enough to say
        # "yes, this batch had traces".
        b = self._make_batch({'traces': {'span_count': 0, 'trace_count': 0}})
        got = _read_snapshot(b)
        self.assertIsNotNone(got)
        self.assertEqual(got.get('span_count'), 0)
