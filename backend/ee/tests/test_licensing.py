"""Enterprise license keys: offline Ed25519 verification, install/remove,
expiry switching features off without touching anything else."""
import base64
import json
from datetime import date, timedelta
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AuditLog
from ee.licensing import keys, store
from ee.licensing.verify import FORMAT, LicenseError, canonical, verify
from ee.models import InstalledLicense
from Organisations.models import Organisations
from Users.models import User
from Utils import edition

KEY = Ed25519PrivateKey.generate()
PUBLIC = base64.b64encode(KEY.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def make_license(features=('saml',), expires=None, key=KEY, **overrides):
    today = timezone.now().date()
    payload = {
        'id': 'lic_test', 'licensee': 'Acme Corp', 'features': list(features),
        'issued': today.isoformat(), 'expires': (expires or today + timedelta(days=365)).isoformat(),
    }
    payload.update(overrides)
    signature = base64.b64encode(key.sign(canonical(payload))).decode()
    return json.dumps({'format': FORMAT, 'payload': payload, 'signature': signature})


class UseTestKey:
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(keys, 'PUBLIC_KEYS', [PUBLIC])
        patcher.start()
        self.addCleanup(patcher.stop)
        store.clear_cache()
        self.addCleanup(store.clear_cache)


class VerifyTest(UseTestKey, SimpleTestCase):
    def test_genuine_key(self):
        lic = verify(make_license(features=['saml', 'scim', 'teleport']))
        self.assertEqual((lic.licensee, lic.features), ('Acme Corp', frozenset({'saml', 'scim'})))
        self.assertFalse(lic.is_expired())

    def test_edited_key_is_rejected(self):
        doc = json.loads(make_license())
        doc['payload']['features'].append('scim')
        with self.assertRaisesMessage(LicenseError, 'signature does not match'):
            verify(json.dumps(doc))

    def test_key_signed_by_someone_else_is_rejected(self):
        with self.assertRaisesMessage(LicenseError, 'signature does not match'):
            verify(make_license(key=Ed25519PrivateKey.generate()))

    def test_malformed_keys(self):
        for text, message in [
            ('', 'empty'), ('not json', 'not valid JSON'), ('{"format": 9}', 'Unknown license key format'),
            ('{"format": 1, "payload": {}}', 'payload and a signature'),
            ('{"format": 1, "payload": {}, "signature": "%%%"}', 'not valid base64'),
        ]:
            with self.subTest(text=text), self.assertRaisesMessage(LicenseError, message):
                verify(text)

    def test_signed_but_incomplete_payload(self):
        with self.assertRaisesMessage(LicenseError, '"expires" is before "issued"'):
            verify(make_license(expires=date(2000, 1, 1)))
        with self.assertRaisesMessage(LicenseError, '"licensee" is missing'):
            verify(make_license(licensee=' '))

    def test_valid_through_the_expiry_day(self):
        lic = verify(make_license(expires=date(2030, 6, 30)))
        self.assertFalse(lic.is_expired(today=date(2030, 6, 30)))
        self.assertTrue(lic.is_expired(today=date(2030, 7, 1)))


class ShippedKeyTest(SimpleTestCase):
    def test_every_shipped_public_key_loads(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        self.assertTrue(keys.PUBLIC_KEYS)
        for encoded in keys.PUBLIC_KEYS:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded))


class LicenseApiTest(UseTestKey, APITestCase):
    def setUp(self):
        super().setUp()
        self.org = Organisations.objects.create(name='Acme')
        self.admin = User.objects.create_user(username='a', email='a@acme.test', password='Pass-word-123',
                                              organisation=self.org, role='admin', is_active=True)
        self.client.force_authenticate(user=self.admin)

    def test_community_until_a_key_is_installed(self):
        self.assertEqual(self.client.get('/api/ee/license/').data, {'status': 'none'})
        summary = self.client.get('/api/organisation/edition/').data
        self.assertEqual((summary['enterprise_available'], summary['features']), (True, []))
        self.assertFalse(edition.has_feature('saml'))

    def test_install_show_and_remove(self):
        response = self.client.put('/api/ee/license/', {'license': make_license(['saml', 'scim'])}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((response.data['status'], response.data['licensee']), ('valid', 'Acme Corp'))
        self.assertNotIn('raw', response.data)
        self.assertTrue(edition.has_feature('scim'))
        self.assertEqual(self.client.get('/api/organisation/edition/').data['features'], ['saml', 'scim'])
        entry = AuditLog.objects.get(organisation=self.org, action='SETTINGS_CHANGE')
        self.assertEqual((entry.details['setting'], entry.details['change']), ('enterprise_license', 'installed'))

        self.assertEqual(self.client.delete('/api/ee/license/').status_code, 204)
        self.assertFalse(InstalledLicense.objects.exists())
        self.assertFalse(edition.has_feature('scim'))
        self.assertEqual(AuditLog.objects.filter(action='SETTINGS_CHANGE', details__change='removed').count(), 1)

    def test_file_upload_replaces_previous_key(self):
        self.client.put('/api/ee/license/', {'license': make_license(['saml'])}, format='json')
        upload = SimpleUploadedFile('acme.license.json', make_license(['scim']).encode())
        response = self.client.put('/api/ee/license/', {'file': upload}, format='multipart')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(InstalledLicense.objects.count(), 1)
        self.assertEqual(sorted(edition.licensed_features()), ['scim'])

    def test_rejects_invalid_and_expired_keys(self):
        bad = self.client.put('/api/ee/license/', {'license': make_license(key=Ed25519PrivateKey.generate())}, format='json')
        self.assertEqual(bad.status_code, 400)
        self.assertIn('signature', bad.data['error'])
        yesterday = timezone.now().date() - timedelta(days=1)
        old = make_license(expires=yesterday, issued=(yesterday - timedelta(days=30)).isoformat())
        expired = self.client.put('/api/ee/license/', {'license': old}, format='json')
        self.assertEqual(expired.status_code, 400)
        self.assertIn('expired', expired.data['error'])
        self.assertFalse(InstalledLicense.objects.exists())

    def test_expiry_switches_features_off_and_keeps_data(self):
        self.client.put('/api/ee/license/', {'license': make_license(['saml'])}, format='json')
        self.assertTrue(edition.has_feature('saml'))
        later = timezone.now() + timedelta(days=400)
        with mock.patch('django.utils.timezone.now', return_value=later):
            store.clear_cache()
            self.assertFalse(edition.has_feature('saml'))
            self.assertEqual(self.client.get('/api/ee/license/').data['status'], 'expired')
            self.assertEqual(self.client.get('/api/organisation/edition/').status_code, 200)
        self.assertTrue(InstalledLicense.objects.exists())

    def test_install_wide_key_needs_license_manage(self):
        Organisations.objects.create(name='Other tenant')  # multi-org: org admins don't hold it
        self.assertEqual(self.client.put('/api/ee/license/', {'license': make_license()}, format='json').status_code, 403)
        self.admin.is_staff = True
        self.admin.save()
        self.assertEqual(self.client.put('/api/ee/license/', {'license': make_license()}, format='json').status_code, 200)

    def test_members_cant_manage_the_key(self):
        user = User.objects.create_user(username='u', email='u@acme.test', password='Pass-word-123',
                                        organisation=self.org, role='user', is_active=True)
        self.client.force_authenticate(user=user)
        self.assertEqual(self.client.get('/api/ee/license/').status_code, 403)
        self.assertEqual(self.client.put('/api/ee/license/', {'license': make_license()}, format='json').status_code, 403)

    def test_key_installed_by_another_process_is_seen_at_once(self):
        # Another web or Celery process installs or removes the key: no cache
        # in this process may hide it (the store reads the row every time).
        self.assertFalse(edition.has_feature('saml'))
        InstalledLicense.objects.create(raw=make_license(['saml']))
        self.assertTrue(edition.has_feature('saml'))
        self.assertEqual(self.client.get('/api/ee/license/').data['status'], 'valid')
        InstalledLicense.objects.all().delete()
        self.assertFalse(edition.has_feature('saml'))
        self.assertEqual(self.client.get('/api/ee/license/').data, {'status': 'none'})

    def test_tampered_row_in_the_database_counts_as_no_license(self):
        InstalledLicense.objects.create(raw=make_license(key=Ed25519PrivateKey.generate()))
        with self.assertLogs('ee.licensing.store', 'WARNING'):
            self.assertFalse(edition.has_feature('saml'))
        self.assertEqual(self.client.get('/api/ee/license/').data['status'], 'invalid')
