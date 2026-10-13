"""
Tests for the GDPR right-to-erasure endpoint
(``DELETE /api/auth/account``).

We cover:
  - the confirmation guard rejects missing / wrong tokens
  - a sole-admin user delete cascades the organisation
  - a non-sole-admin user delete leaves the organisation intact
  - every Knox token the user owned is revoked
  - one ACCOUNT_DELETE (or ORG_DELETE) AuditLog row is written
"""

from knox.models import AuthToken
from rest_framework import status
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations
from Users.models import User


class DeleteAccountTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='GDPR Org')
        self.admin = User.objects.create_user(
            username='gdpradmin', email='gdpradmin@test.com',
            password='Pass1234!', organisation=self.org,
            role='admin', is_active=True,
        )
        # Pre-create two active tokens so we can assert they get burned.
        AuthToken.objects.create(self.admin)
        AuthToken.objects.create(self.admin)

    def _auth(self, user):
        self.client.force_authenticate(user=user)

    def test_missing_confirmation_returns_400(self):
        self._auth(self.admin)
        response = self.client.delete('/api/auth/account', {}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_wrong_confirmation_returns_400(self):
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'yes'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_sole_admin_delete_removes_user_and_org(self):
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.admin.pk).exists())
        self.assertFalse(Organisations.objects.filter(pk=self.org.pk).exists())

    def test_non_sole_admin_delete_keeps_org(self):
        # Add a second admin so self.admin is no longer the only one.
        User.objects.create_user(
            username='coadmin', email='coadmin@test.com',
            password='Pass1234!', organisation=self.org,
            role='admin', is_active=True,
        )
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(Organisations.objects.filter(pk=self.org.pk).exists())

    def test_delete_revokes_all_user_tokens(self):
        self.assertEqual(AuthToken.objects.filter(user=self.admin).count(), 2)
        self._auth(self.admin)
        # Sole admin → org cascade also nukes tokens, but we want to be
        # sure they're gone regardless of which path the view took.
        self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(AuthToken.objects.filter(user_id=self.admin.pk).count(), 0)

    def test_audit_log_row_is_written_for_non_sole_admin_path(self):
        # When the org survives the delete, the AuditLog row also survives
        # (CASCADE on org would otherwise blow it away).
        User.objects.create_user(
            username='coadmin', email='coadmin@test.com',
            password='Pass1234!', organisation=self.org,
            role='admin', is_active=True,
        )
        self._auth(self.admin)
        self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        log = AuditLog.objects.filter(
            organisation=self.org, action='ACCOUNT_DELETE',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details['deleted_user_email'], 'gdpradmin@test.com')
        self.assertFalse(log.details['org_deleted'])

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        # IsAuthenticated returns 401 with no creds; the user remains.
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
