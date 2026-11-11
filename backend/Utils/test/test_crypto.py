"""Stored secrets have their own key, can change it, and fail loudly."""
import base64
import hashlib
from io import StringIO

from cryptography.fernet import Fernet
from django.apps import apps
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from Data.management.commands.rotate_secrets import DICT_FIELDS, STRING_FIELDS
from Organisations.models import Organisations
from Users.models import SecuritySettings
from Utils import crypto
from api.settings import _encryption_key_valid
from integrations.models import ObservabilityIntegration

OLD = Fernet.generate_key().decode()
NEW = Fernet.generate_key().decode()


def legacy(text, secret_key=None):
    """A value as releases before the dedicated key wrote it."""
    key = base64.urlsafe_b64encode(hashlib.sha256((secret_key or settings.SECRET_KEY).encode()).digest())
    return Fernet(key).encrypt(text.encode()).decode()


@override_settings(SEROPS_ENCRYPTION_KEY=NEW, SEROPS_ENCRYPTION_KEY_PREVIOUS=[])
class CryptoTest(SimpleTestCase):
    def test_round_trip_is_tagged(self):
        value = crypto.encrypt('s3cret')
        self.assertTrue(value.startswith('v1:'))
        self.assertEqual(crypto.decrypt(value), 's3cret')

    def test_does_not_depend_on_the_django_secret_key(self):
        value = crypto.encrypt('s3cret')
        with override_settings(SECRET_KEY='another-signing-key-of-sufficient-length'):
            self.assertEqual(crypto.decrypt(value), 's3cret')

    def test_old_values_stay_readable(self):
        self.assertEqual(crypto.decrypt(legacy('old')), 'old')
        self.assertTrue(crypto.needs_rewrite(legacy('old')))

    def test_previous_key_reads_but_needs_rewrite(self):
        with override_settings(SEROPS_ENCRYPTION_KEY=OLD):
            value = crypto.encrypt('s3cret')
        with override_settings(SEROPS_ENCRYPTION_KEY_PREVIOUS=[OLD]):
            self.assertEqual(crypto.decrypt(value), 's3cret')
            self.assertTrue(crypto.needs_rewrite(value))

    def test_wrong_key_raises_and_does_not_return_empty(self):
        with override_settings(SEROPS_ENCRYPTION_KEY=OLD):
            value = crypto.encrypt('s3cret')
        with self.assertRaises(crypto.DecryptionError), self.assertLogs('Utils.crypto', 'ERROR'):
            crypto.decrypt(value)

    def test_key_format_is_checked_at_startup(self):
        self.assertTrue(_encryption_key_valid(NEW))
        for bad in ('', 'too-short', 'change-me-generate-a-real-one'):
            self.assertFalse(_encryption_key_valid(bad))

    def test_rotation_knows_real_fields(self):
        for label, field in STRING_FIELDS:
            apps.get_model(label)._meta.get_field(field)
        for label, field, _ in DICT_FIELDS:
            apps.get_model(label)._meta.get_field(field)


@override_settings(SEROPS_ENCRYPTION_KEY=NEW, SEROPS_ENCRYPTION_KEY_PREVIOUS=[])
class RotateSecretsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Rotate', website='https://rotate.test')
        self.sso = SecuritySettings.objects.create(organisation=self.org, sso_client_secret_encrypted=legacy('sso'))
        self.integration = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='elasticsearch', display_name='es', host='https://es.test:9200')
        ObservabilityIntegration.objects.filter(pk=self.integration.pk).update(
            password=legacy('pw'), extra_config={'api_key': legacy('dd'), 'index': 'logs-*'})

    def _run(self, *args):
        out = StringIO()
        call_command('rotate_secrets', *args, stdout=out)
        return out.getvalue()

    def test_rewrites_and_survives_a_new_signing_key(self):
        self.assertIn('Re-encrypted 3', self._run())
        self.sso.refresh_from_db()
        self.integration.refresh_from_db()
        self.assertTrue(self.sso.sso_client_secret_encrypted.startswith('v1:'))
        self.assertEqual(self.integration.extra_config['index'], 'logs-*')
        with override_settings(SECRET_KEY='a-completely-different-signing-key-now'):
            self.assertEqual(self.sso.get_client_secret(), 'sso')
            self.assertEqual(self.integration.get_password(), 'pw')
            self.assertEqual(crypto.decrypt(self.integration.extra_config['api_key']), 'dd')

    def test_second_run_changes_nothing(self):
        self._run()
        self.assertIn('Re-encrypted 0', self._run())

    def test_dry_run_writes_nothing(self):
        before = self.sso.sso_client_secret_encrypted
        self.assertIn('Would re-encrypt 3', self._run('--dry-run'))
        self.sso.refresh_from_db()
        self.assertEqual(self.sso.sso_client_secret_encrypted, before)

    def test_key_change_with_previous(self):
        self._run()
        with override_settings(SEROPS_ENCRYPTION_KEY=OLD, SEROPS_ENCRYPTION_KEY_PREVIOUS=[NEW]):
            self.assertIn('Re-encrypted 3', self._run())
        with override_settings(SEROPS_ENCRYPTION_KEY=OLD):
            self.sso.refresh_from_db()
            self.assertEqual(self.sso.get_client_secret(), 'sso')

    def test_unreadable_value_is_named_and_kept(self):
        bad = legacy('x', 'not-the-key-this-install-uses')
        SecuritySettings.objects.filter(pk=self.sso.pk).update(sso_client_secret_encrypted=bad)
        with self.assertRaisesMessage(CommandError, f'Users.SecuritySettings {self.sso.pk} sso_client_secret_encrypted'):
            self._run()
        self.sso.refresh_from_db()
        self.assertEqual(self.sso.sso_client_secret_encrypted, bad)
        self.integration.refresh_from_db()
        self.assertTrue(self.integration.password.startswith('v1:'))
