"""Secret ``extra_config`` values are encrypted at rest and never returned.

Datadog's ``api_key``/``app_key`` and the bearer tokens used to sit in plain
JSON, and the detail endpoint — open to every org member, viewers
included — returned them verbatim.
"""

import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User
from integrations.models import ObservabilityIntegration


def _stored_extra_config(integration):
    """The JSON exactly as it sits in the database."""
    return ObservabilityIntegration.objects.values_list(
        'extra_config', flat=True,
    ).get(pk=integration.pk)


class SecretStorageTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='Secret Org', website='https://s.test')

    def _datadog(self, **extra):
        return ObservabilityIntegration.objects.create(
            organisation=self.org, provider='datadog', display_name='DD',
            capabilities=['logs'], host='datadoghq.com',
            extra_config={'site': 'datadoghq.eu', **extra},
        )

    def test_secrets_are_encrypted_in_the_database(self):
        integration = self._datadog(api_key='dd-api', app_key='dd-app')
        stored = _stored_extra_config(integration)
        self.assertNotEqual(stored['api_key'], 'dd-api')
        self.assertNotEqual(stored['app_key'], 'dd-app')
        self.assertEqual(stored['site'], 'datadoghq.eu')

    def test_adapter_config_gets_plaintext(self):
        integration = self._datadog(api_key='dd-api', app_key='dd-app')
        integration.refresh_from_db()
        config = integration.get_config()
        self.assertEqual(config['api_key'], 'dd-api')
        self.assertEqual(config['app_key'], 'dd-app')
        self.assertEqual(config['site'], 'datadoghq.eu')

    def test_saving_again_does_not_double_encrypt(self):
        integration = self._datadog(api_key='dd-api')
        integration.refresh_from_db()
        integration.display_name = 'Renamed'
        integration.save()
        integration.refresh_from_db()
        self.assertEqual(integration.get_config()['api_key'], 'dd-api')

    def test_empty_secret_is_dropped(self):
        integration = self._datadog(api_key='')
        self.assertNotIn('api_key', _stored_extra_config(integration))

    def test_dict_credentials_are_serialised_before_encryption(self):
        integration = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='gcp', display_name='GCP',
            capabilities=['logs'],
            extra_config={'project_id': 'p', 'credentials_json': {'type': 'service_account'}},
        )
        integration.refresh_from_db()
        self.assertEqual(
            integration.get_config()['credentials_json'], '{"type": "service_account"}',
        )

    def test_secret_fields_set_lists_only_present_secrets(self):
        integration = self._datadog(api_key='dd-api', tenant_id='not-a-secret')
        self.assertEqual(integration.secret_fields_set(), ['api_key'])


class SecretMigrationTest(TestCase):

    def test_migration_encrypts_plaintext_rows(self):
        org = Organisations.objects.create(name='Mig Org', website='https://m.test')
        integration = ObservabilityIntegration.objects.create(
            organisation=org, provider='prometheus', display_name='Prom',
            capabilities=['metrics'], host='http://prom:9090',
        )
        # A row written before this release: plain value, bypassing save().
        ObservabilityIntegration.objects.filter(pk=integration.pk).update(
            extra_config={'bearer_token': 'plain-token'},
        )
        migration = importlib.import_module(
            'integrations.migrations.0010_encrypt_extra_config_secrets',
        )
        migration.encrypt_existing(django_apps, None)

        self.assertNotEqual(_stored_extra_config(integration)['bearer_token'], 'plain-token')
        integration.refresh_from_db()
        self.assertEqual(integration.get_config()['bearer_token'], 'plain-token')


class SecretApiTest(APITestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='Api Org', website='https://a.test')
        self.admin = User.objects.create_user(
            username='secadmin', email='sa@test.com', password='Test123!',
            organisation=self.org, role='admin', is_active=True,
        )
        self.viewer = User.objects.create_user(
            username='secviewer', email='sv@test.com', password='Test123!',
            organisation=self.org, role='viewer', is_active=True,
        )
        self.integration = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='datadog', display_name='DD',
            capabilities=['logs'], host='datadoghq.com',
            extra_config={'site': 'datadoghq.eu', 'api_key': 'dd-api', 'app_key': 'dd-app'},
        )
        self.detail_url = reverse(
            'observability-integration-detail', kwargs={'pk': self.integration.pk},
        )
        self.list_url = reverse('observability-integration-list')

    def _assert_no_secrets(self, item):
        self.assertNotIn('api_key', item['extra_config'])
        self.assertNotIn('app_key', item['extra_config'])
        self.assertEqual(item['extra_config']['site'], 'datadoghq.eu')
        self.assertEqual(item['secret_fields_set'], ['api_key', 'app_key'])
        self.assertNotIn('dd-api', str(item))

    def test_viewer_detail_does_not_include_secrets(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_no_secrets(response.data)

    def test_viewer_list_does_not_include_secrets(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self._assert_no_secrets(response.data[0])

    def test_blank_secret_on_edit_keeps_the_stored_one(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            self.detail_url,
            {'extra_config': {'site': 'us5.datadoghq.com', 'api_key': ''}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.integration.refresh_from_db()
        config = self.integration.get_config()
        self.assertEqual(config['site'], 'us5.datadoghq.com')
        self.assertEqual(config['api_key'], 'dd-api')
        self.assertEqual(config['app_key'], 'dd-app')

    def test_new_secret_on_edit_replaces_the_stored_one(self):
        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            self.detail_url,
            {'extra_config': {'site': 'datadoghq.eu', 'api_key': 'rotated'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.get_config()['api_key'], 'rotated')
        self.assertNotIn('rotated', str(response.data))

    def test_create_encrypts_and_hides_secrets(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(self.list_url, {
            'provider': 'prometheus', 'display_name': 'Prom',
            'capabilities': ['metrics'], 'host': 'http://prom:9090',
            'extra_config': {'bearer_token': 'prom-token'},
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn('bearer_token', response.data['extra_config'])
        self.assertEqual(response.data['secret_fields_set'], ['bearer_token'])
        created = ObservabilityIntegration.objects.get(pk=response.data['id'])
        self.assertNotEqual(_stored_extra_config(created)['bearer_token'], 'prom-token')
        self.assertEqual(created.get_config()['bearer_token'], 'prom-token')
