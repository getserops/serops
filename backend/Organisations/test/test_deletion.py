"""Deleting an organisation that is still receiving telemetry."""
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from Organisations.deletion import delete_organisation
from Organisations.models import Organisations
from traces.models import IngestKey


class DeleteOrganisationTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='Leaving')
        self.key = IngestKey.objects.create(organisation=self.org, name='k8s', key_hash='a' * 64, key_prefix='sk_test')

    def test_ingest_keys_stop_working_first(self):
        seen = {}

        def delete(*a, **k):
            seen['active'] = IngestKey.objects.get(pk=self.key.pk).is_active
            return original(*a, **k)
        original = Organisations.delete
        with patch.object(Organisations, 'delete', autospec=True, side_effect=delete):
            delete_organisation(self.org)
        self.assertFalse(seen['active'])
        self.assertFalse(Organisations.objects.filter(pk=self.org.pk).exists())

    def test_a_row_arriving_during_deletion_is_retried(self):
        original = Organisations.delete
        calls = []

        def delete(org, *a, **k):
            calls.append(1)
            if len(calls) == 1:
                raise IntegrityError('violates foreign key constraint "traces_trace_organisation_id"')
            return original(org, *a, **k)
        with patch.object(Organisations, 'delete', autospec=True, side_effect=delete), \
                patch('Organisations.deletion.time.sleep'):
            delete_organisation(self.org)
        self.assertEqual(len(calls), 2)
        self.assertFalse(Organisations.objects.filter(pk=self.org.pk).exists())

    def test_traces_are_purged_in_chunks_before_the_cascade(self):
        from datetime import timedelta
        from django.utils import timezone
        from traces.models import Span, Trace
        other = Organisations.objects.create(name='Staying')
        now = timezone.now()
        for org, prefix in ((self.org, 'a'), (other, 'b')):
            for i in range(5):
                t = Trace.objects.create(trace_id=f'{prefix}{i:031d}', organisation=org,
                                         start_time=now, end_time=now + timedelta(seconds=1))
                Span.objects.create(trace=t, span_id=f'{i:016d}', operation_name='op', duration_ms=1000,
                                    start_time=now, end_time=now + timedelta(seconds=1))
        with patch('Organisations.deletion.TELEMETRY_CHUNK', 2):
            from Organisations import deletion
            deletion._purge_telemetry(self.org, chunk=2)
        self.assertEqual(Trace.objects.filter(organisation=self.org).count(), 0)
        self.assertEqual(Span.objects.filter(trace__organisation=other).count(), 5)
        delete_organisation(self.org)
        self.assertFalse(Organisations.objects.filter(pk=self.org.pk).exists())
        self.assertEqual(Trace.objects.filter(organisation=other).count(), 5)

    def test_it_gives_up_after_the_attempts(self):
        with patch.object(Organisations, 'delete', autospec=True, side_effect=IntegrityError('fk')), \
                patch('Organisations.deletion.time.sleep'):
            with self.assertRaises(IntegrityError):
                delete_organisation(self.org, attempts=2)
