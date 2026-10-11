"""Q5-5 (2026-09-21): per-org alert-ingest secret + rotation + auth."""
from __future__ import annotations
import hashlib

from django.test import TestCase, RequestFactory
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User


def _sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


class AlertSecretRotationTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='q5-5-org')
        self.admin = User.objects.create_user(
            username='q5admin', email='q5admin@example.com',
            password='pw', organisation=self.org, role='admin',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_reveal_initially_says_no_secret(self):
        r = self.client.get('/api/organisation/alert-secret/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['has_secret'])
        self.assertEqual(r.data['prefix'], '')

    def test_rotate_returns_plaintext_and_stores_only_hash(self):
        r = self.client.post('/api/organisation/alert-secret/rotate/')
        self.assertEqual(r.status_code, 200)
        plaintext = r.data['plaintext']
        self.assertTrue(plaintext.startswith('serops_alert_'))
        self.org.refresh_from_db()
        self.assertEqual(self.org.alert_ingest_secret_hash, _sha(plaintext))
        # Prefix stored, full plaintext not
        self.assertTrue(self.org.alert_ingest_secret_prefix)
        self.assertNotEqual(self.org.alert_ingest_secret_prefix, plaintext)
        self.assertIsNotNone(self.org.alert_ingest_secret_rotated_at)

    def test_rotate_supersedes_old_secret(self):
        r1 = self.client.post('/api/organisation/alert-secret/rotate/')
        old = r1.data['plaintext']
        r2 = self.client.post('/api/organisation/alert-secret/rotate/')
        new = r2.data['plaintext']
        self.assertNotEqual(old, new)
        self.org.refresh_from_db()
        self.assertEqual(self.org.alert_ingest_secret_hash, _sha(new))
        self.assertNotEqual(self.org.alert_ingest_secret_hash, _sha(old))


class AlertWebhookAuthTest(TestCase):
    """The webhook auth path checks per-org hash first, then falls back
    to global settings. Verify both branches."""

    def setUp(self):
        self.org = Organisations.objects.create(name='q5-5-auth-org')

    def _auth(self, provided):
        from Data.alert_webhooks import _authenticate
        rf = RequestFactory()
        req = rf.post('/api/webhooks/alerts/alertmanager/1/',
                      HTTP_AUTHORIZATION=f'Bearer {provided}')
        return _authenticate(req, 'alertmanager', self.org)

    def test_per_org_hash_accepts_matching_plaintext(self):
        plaintext = 'serops_alert_abc123'
        self.org.alert_ingest_secret_hash = _sha(plaintext)
        self.org.save(update_fields=['alert_ingest_secret_hash'])
        self.assertTrue(self._auth(plaintext))

    def test_per_org_hash_rejects_wrong_plaintext(self):
        plaintext = 'serops_alert_abc123'
        self.org.alert_ingest_secret_hash = _sha(plaintext)
        self.org.save(update_fields=['alert_ingest_secret_hash'])
        self.assertFalse(self._auth('serops_alert_wrong'))

    def test_no_bearer_header_rejected(self):
        from Data.alert_webhooks import _authenticate
        rf = RequestFactory()
        req = rf.post('/api/webhooks/alerts/alertmanager/1/')
        self.assertFalse(_authenticate(req, 'alertmanager', self.org))

    def test_falls_back_to_global_when_no_per_org(self):
        from django.test import override_settings
        with override_settings(ALERT_WEBHOOK_SECRETS={'alertmanager': 'legacy-global'}):
            self.assertTrue(self._auth('legacy-global'))
            self.assertFalse(self._auth('wrong'))
