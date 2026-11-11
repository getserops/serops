"""
Tests for the GDPR right-to-erasure endpoint
(``DELETE /api/auth/account``).

We cover:
  - the confirmation guard rejects missing / wrong tokens
  - the sole admin is refused and nothing is deleted
  - a non-sole-admin user delete leaves the organisation intact
  - every Knox token the user owned is revoked
  - one ACCOUNT_DELETE AuditLog row is written, with no email in it
  - the deleted email is gone from the audit log
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

    def _co_admin(self):
        return User.objects.create_user(
            username='coadmin', email='coadmin@test.com',
            password='Pass1234!', organisation=self.org,
            role='admin', is_active=True,
        )

    def test_sole_admin_is_refused_and_nothing_is_deleted(self):
        member = User.objects.create_user(
            username='member', email='member@test.com', password='Pass1234!',
            organisation=self.org, role='user', is_active=True,
        )
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
        self.assertTrue(User.objects.filter(pk=member.pk).exists())
        self.assertTrue(Organisations.objects.filter(pk=self.org.pk).exists())

    def test_inactive_co_admin_does_not_count(self):
        co_admin = self._co_admin()
        User.objects.filter(pk=co_admin.pk).update(is_active=False)
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_email_is_replaced_across_the_audit_log(self):
        self._co_admin()
        other_org = Organisations.objects.create(name='Elsewhere')
        kept = AuditLog.objects.create(
            organisation=self.org, user=self.admin, action='LOGIN',
            details={'email': 'gdpradmin@test.com'})
        cased = AuditLog.objects.create(
            organisation=other_org, action='TEAM_INVITE',
            details={'affected_user': 'GDPRadmin@Test.com', 'role': 'user'})
        nested = AuditLog.objects.create(
            organisation=self.org, action='SSO_DENIED',
            details={'context': {'note': 'refused gdpradmin@test.com today'}})
        someone_else = AuditLog.objects.create(
            organisation=self.org, action='LOGIN', details={'email': 'coadmin@test.com'})
        pk = self.admin.pk
        self._auth(self.admin)
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        for row in (kept, cased, nested, someone_else):
            row.refresh_from_db()
        self.assertEqual(kept.details, {'email': f'user:{pk}'})
        self.assertEqual(cased.details, {'affected_user': f'user:{pk}', 'role': 'user'})
        self.assertEqual(nested.details['context']['note'], f'refused user:{pk} today')
        self.assertEqual(someone_else.details, {'email': 'coadmin@test.com'})
        self.assertFalse(AuditLog.objects.filter(details__icontains='gdpradmin@test.com').exists())

    def test_views_log_no_email_addresses(self):
        import re
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / 'Users' / 'views.py').read_text(encoding='utf-8')
        offending = re.findall(r'logger\.\w+\(.*\{(?:\w+\.)*email\}.*', source)
        self.assertEqual(offending, [])

    def test_non_sole_admin_delete_keeps_org(self):
        self._co_admin()
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
        self._co_admin()
        self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        self.assertEqual(AuthToken.objects.filter(user_id=self.admin.pk).count(), 0)

    def test_audit_log_row_is_written_for_non_sole_admin_path(self):
        self.admin_pk = self.admin.pk
        self._co_admin()
        self._auth(self.admin)
        self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        log = AuditLog.objects.filter(
            organisation=self.org, action='ACCOUNT_DELETE',
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.details, {'deleted_user_id': self.admin_pk})

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.delete(
            '/api/auth/account', {'confirm': 'DELETE'}, format='json',
        )
        # IsAuthenticated returns 401 with no creds; the user remains.
        self.assertIn(response.status_code, (401, 403))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())
