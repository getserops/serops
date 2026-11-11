"""
Changing the login email takes the password and the new mailbox.

It used to be a plain profile update, so a stolen token could move the account
to the thief's address for good, and anyone could squat an address another
organisation's SSO claims.
"""
from unittest.mock import patch

from django.core import mail, signing
from django.test import override_settings
from knox.models import AuthToken
from rest_framework.test import APITestCase

from Data.models import AuditLog
from Organisations.models import Organisations
from Users.models import SecuritySettings, User
from Utils.email_utils import make_email_change_token

PASSWORD = 'TestPass123!'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', REACT_URL='https://app.test')
class EmailChangeTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Org', website='https://org.test')
        self.user = User.objects.create_user(
            username='u', email='old@example.com', password=PASSWORD, organisation=self.org, role='user', is_active=True)
        self.client.force_authenticate(user=self.user)
        patcher = patch('Utils.email_utils._get_connection_and_from', return_value=(None, 'serops@test'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def _change(self, email='new@example.com', password=PASSWORD, **extra):
        return self.client.post('/api/auth/profile', {'email': email, 'current_password': password, **extra}, format='json')

    def _confirm(self, token):
        self.client.force_authenticate(user=None)
        return self.client.post(f'/api/auth/email/confirm/{token}')

    def _email(self):
        self.user.refresh_from_db()
        return self.user.email

    def test_asking_sends_a_link_and_changes_nothing_yet(self):
        response = self._change(first_name='Ada')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email_change_pending'], 'new@example.com')
        self.assertEqual(self._email(), 'old@example.com')
        self.assertEqual(self.user.first_name, 'Ada')
        self.assertEqual(mail.outbox[0].to, ['new@example.com'])
        self.assertIn('https://app.test/email/confirm/', mail.outbox[0].body)

    def test_a_stolen_token_without_the_password_cannot_change_it(self):
        for password in ('wrong-password', ''):
            self.assertEqual(self._change(password=password).status_code, 400)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(self._email(), 'old@example.com')

    def test_saving_the_profile_with_the_same_email_needs_no_password(self):
        response = self.client.post('/api/auth/profile', {'email': 'OLD@example.com', 'first_name': 'Ada'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('email_change_pending', response.data)
        self.assertEqual(self._email(), 'old@example.com')

    def test_sso_accounts_keep_the_email_of_their_identity_provider(self):
        self.user.set_unusable_password()
        self.user.save()
        self.assertEqual(self._change().status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_address_of_another_user_is_refused(self):
        User.objects.create_user(username='t', email='taken@example.com', password=PASSWORD, organisation=self.org)
        self.assertEqual(self._change(email='Taken@example.com').status_code, 400)

    def test_malformed_address_is_refused(self):
        self.assertEqual(self._change(email='not-an-email').status_code, 400)

    def test_domain_claimed_by_another_organisations_sso_is_refused(self):
        other = Organisations.objects.create(name='Corp', website='https://corp.test')
        SecuritySettings.objects.create(organisation=other, sso_enabled=True, sso_provider='oidc', sso_domains=['corp.example'])
        self.assertEqual(self._change(email='cfo@corp.example').status_code, 400)
        self.assertEqual(mail.outbox, [])

    def test_own_organisations_sso_domain_is_allowed(self):
        SecuritySettings.objects.create(organisation=self.org, sso_enabled=True, sso_provider='oidc', sso_domains=['corp.example'])
        self.assertEqual(self._change(email='me@corp.example').status_code, 200)

    def test_says_so_when_the_mail_cannot_be_sent(self):
        with patch('Utils.email_utils._send_plain', side_effect=OSError('smtp down')):
            self.assertEqual(self._change().status_code, 502)

    def test_link_changes_the_email_ends_sessions_and_tells_the_old_address(self):
        AuthToken.objects.create(self.user)
        response = self._confirm(make_email_change_token(self.user, 'new@example.com'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._email(), 'new@example.com')
        self.assertEqual(AuthToken.objects.filter(user=self.user).count(), 0)
        self.assertEqual(mail.outbox[-1].to, ['old@example.com'])
        entry = AuditLog.objects.get(organisation=self.org, action='SETTINGS_CHANGE')
        self.assertEqual(entry.details['setting'], 'account_email')
        self.assertEqual(entry.user, self.user)

    def test_link_works_once(self):
        token = make_email_change_token(self.user, 'new@example.com')
        self.assertEqual(self._confirm(token).status_code, 200)
        self.assertEqual(self._confirm(token).status_code, 400)

    def test_a_password_change_cancels_the_link(self):
        token = make_email_change_token(self.user, 'new@example.com')
        self.user.set_password('Another-Pass-456')
        self.user.save()
        self.assertEqual(self._confirm(token).status_code, 400)
        self.assertEqual(self._email(), 'old@example.com')

    def test_expired_link_is_refused(self):
        token = make_email_change_token(self.user, 'new@example.com')
        with patch('Utils.email_utils.EMAIL_CHANGE_MAX_AGE', -1):
            self.assertEqual(self._confirm(token).status_code, 400)
        self.assertEqual(self._email(), 'old@example.com')

    def test_forged_link_is_refused(self):
        forged = signing.dumps({'user': self.user.pk, 'old': 'old@example.com', 'new': 'x@e.com', 'pw': 'x'}, salt='other')
        self.assertEqual(self._confirm(forged).status_code, 400)

    def test_address_taken_since_the_request_is_refused(self):
        token = make_email_change_token(self.user, 'new@example.com')
        User.objects.create_user(username='t', email='new@example.com', password=PASSWORD, organisation=self.org)
        self.assertEqual(self._confirm(token).status_code, 400)
        self.assertEqual(self._email(), 'old@example.com')
