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

    def test_it_gives_up_after_the_attempts(self):
        with patch.object(Organisations, 'delete', autospec=True, side_effect=IntegrityError('fk')), \
                patch('Organisations.deletion.time.sleep'):
            with self.assertRaises(IntegrityError):
                delete_organisation(self.org, attempts=2)
