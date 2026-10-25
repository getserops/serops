from unittest.mock import patch, mock_open, MagicMock
from datetime import timedelta

from django.urls import reverse
from django.conf import settings
from django.test import override_settings
from django.core import signing
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase
from knox.models import AuthToken

from Users.models import User
from Organisations.models import Organisations


# =============================================================================
# RegisterView
# =============================================================================

# These exercise the registration flow itself, so they run on an instance
# with registration explicitly open: in the default automatic mode, the
# users some tests create would close it (see test_registration_gate).
@override_settings(REGISTRATION_ENABLED=True)
class TestRegisterView(APITestCase):
    """Tests for user registration endpoint."""

    def setUp(self):
        self.url = reverse('register')
        self.valid_data = {
            'invite_code': settings.BETA_INVITE_CODE,
            'user': {
                'email': 'newuser@example.com',
                'password': 'TestPass123!',
                'password_confirmation': 'TestPass123!',
                'first_name': 'New',
                'last_name': 'User',
                'phone': '1234567890',
                'username': 'newuser',
            },
            'organisation': {
                'name': 'New Org',
                'website': 'https://neworg.com',
            },
        }

    # EMAIL_HOST pinned explicitly. RegisterView branches on
    # has_working_smtp_config(), which is just bool(EMAIL_HOST): with SMTP the
    # user stays inactive and gets a verification link, without it the account
    # auto-activates. These two tests assert the SMTP branch, so leaving the
    # setting to the environment made them pass only on a machine with a
    # populated .env and fail on every clean checkout — including CI — for
    # reasons that look nothing like the cause.
    @override_settings(EMAIL_HOST='smtp.example.test')
    @patch('Users.views.send_activation_link')
    def test_register_success(self, mock_send):
        response = self.client.post(self.url, self.valid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertFalse(user.is_active)
        self.assertTrue(Organisations.objects.filter(name='New Org').exists())

    @override_settings(EMAIL_HOST='')
    @patch('Users.views.send_activation_link')
    def test_register_auto_activates_when_no_smtp(self, mock_send):
        """The other branch, which nothing covered: a self-host with no mail
        server must not strand its first user behind a verification email it
        can never send."""
        response = self.client.post(self.url, self.valid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(email='newuser@example.com')
        self.assertTrue(user.is_active, 'no SMTP means the account must be usable immediately')
        mock_send.assert_not_called()

    @patch('Users.views.send_activation_link')
    def test_register_password_mismatch(self, mock_send):
        data = {**self.valid_data}
        data['user'] = {**data['user'], 'password_confirmation': 'WrongPass!'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('Users.views.send_activation_link')
    def test_register_duplicate_email(self, mock_send):
        self.client.post(self.url, self.valid_data, format='json')
        data2 = {**self.valid_data}
        data2['organisation'] = {'name': 'Another Org', 'website': 'https://another.com'}
        response = self.client.post(self.url, data2, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('Users.views.send_activation_link')
    def test_register_missing_fields(self, mock_send):
        data = {
            'invite_code': settings.BETA_INVITE_CODE,
            'user': {},
            'organisation': {},
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('Users.views.send_activation_link')
    def test_register_rejects_weak_password(self, mock_send):
        """AUTH_PASSWORD_VALIDATORS must fire through the serializer.

        Prior to BE-P1-05 (audit 2026-09-05) the register view accepted
        password='123' — Django's validators are configured in settings
        but DRF serializers don't invoke them automatically. Regression
        guard: any password shorter than MinimumLengthValidator's floor
        (8) OR on the common-password list MUST 400.
        """
        data = {**self.valid_data}
        data['user'] = {
            **data['user'],
            'password': '123',
            'password_confirmation': '123',
        }
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Error should surface under the 'password' key so the frontend
        # can show a targeted message rather than "something's wrong."
        self.assertIn('password', response.data)

    @patch('Users.views.send_activation_link')
    def test_register_user_role_is_admin(self, mock_send):
        self.client.post(self.url, self.valid_data, format='json')
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.role, 'admin')

    @override_settings(EMAIL_HOST='smtp.example.test')
    @patch('Users.views.send_activation_link')
    def test_register_sends_activation_email(self, mock_send):
        self.client.post(self.url, self.valid_data, format='json')
        mock_send.assert_called_once()

    @override_settings(EMAIL_HOST='smtp.example.test')
    @patch('Users.views.send_activation_link', return_value=True)
    def test_register_says_the_email_was_sent(self, mock_send):
        response = self.client.post(self.url, self.valid_data, format='json')
        self.assertIs(response.data['email_sent'], True)
        self.assertIn('check your email', response.data['message'])

    @override_settings(EMAIL_HOST='smtp.example.test')
    @patch('Users.views.send_activation_link', return_value=False)
    def test_register_says_when_the_email_failed(self, mock_send):
        """A mail server that refuses the message used to show up only in
        the backend log while sign-up said "check your email"."""
        response = self.client.post(self.url, self.valid_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIs(response.data['email_sent'], False)
        self.assertIn('could not be sent', response.data['message'])


# =============================================================================
# LoginView
# =============================================================================

class TestLoginView(APITestCase):
    """Tests for user login endpoint."""

    def setUp(self):
        self.url = reverse('login')
        self.org = Organisations.objects.create(name='Login Org', website='https://login.com')
        self.user = User.objects.create_user(
            username='loginuser',
            email='login@example.com',
            password='TestPass123!',
            first_name='Login',
            last_name='User',
            organisation=self.org,
            role='admin',
            is_active=True,
        )

    @patch('Users.views.log_login')
    def test_login_success(self, mock_log):
        response = self.client.post(self.url, {
            'email': 'login@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('token', response.data)
        self.assertIn('user', response.data)
        self.assertEqual(response.data['user']['email'], 'login@example.com')
        self.assertEqual(response.data['user']['role'], 'admin')
        self.assertEqual(response.data['user']['organisation'], 'Login Org')

    @patch('Users.views.log_login')
    def test_login_wrong_password(self, mock_log):
        response = self.client.post(self.url, {
            'email': 'login@example.com',
            'password': 'WrongPassword!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('Users.views.log_login')
    def test_login_nonexistent_email(self, mock_log):
        response = self.client.post(self.url, {
            'email': 'nonexistent@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('Users.views.log_login')
    def test_login_inactive_user(self, mock_log):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {
            'email': 'login@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    @patch('Users.views.log_login')
    def test_login_suspended_user(self, mock_log):
        self.user.status = 'suspended'
        self.user.save()
        response = self.client.post(self.url, {
            'email': 'login@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('Users.views.log_login')
    def test_login_disabled_user(self, mock_log):
        self.user.status = 'disabled'
        self.user.save()
        response = self.client.post(self.url, {
            'email': 'login@example.com',
            'password': 'TestPass123!',
        })
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_email(self):
        response = self.client.post(self.url, {'password': 'TestPass123!'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_missing_password(self):
        response = self.client.post(self.url, {'email': 'login@example.com'})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# =============================================================================
# LogoutView
# =============================================================================

class TestLogoutView(APITestCase):
    """Tests for user logout endpoint."""

    def setUp(self):
        self.url = reverse('logout')
        self.org = Organisations.objects.create(name='Logout Org', website='https://logout.com')
        self.user = User.objects.create_user(
            username='logoutuser',
            email='logout@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )

    @patch('Users.views.log_logout')
    def test_logout_success(self, mock_log):
        instance, token = AuthToken.objects.create(self.user)
        self.client.force_authenticate(user=self.user, token=instance)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_logout_unauthenticated(self):
        response = self.client.post(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))


# =============================================================================
# EmailVerification
# =============================================================================

class TestEmailVerification(APITestCase):
    """Tests for email verification endpoint."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Verify Org', website='https://verify.com')
        self.user = User.objects.create_user(
            username='verifyuser',
            email='verify@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=False,
        )

    def test_verify_valid_token(self):
        token = signing.dumps(self.user.pk)
        url = reverse('activate', kwargs={'token': token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_verify_invalid_token(self):
        url = reverse('activate', kwargs={'token': 'invalid-token-string'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    @patch('Users.views.signing.loads', side_effect=signing.SignatureExpired('expired'))
    def test_verify_expired_token(self, mock_loads):
        url = reverse('activate', kwargs={'token': 'some-expired-token'})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)

    def test_verify_already_active(self):
        self.user.is_active = True
        self.user.save()
        token = signing.dumps(self.user.pk)
        url = reverse('activate', kwargs={'token': token})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('already activated', response.data.get('message', ''))


# =============================================================================
# ProfileView
# =============================================================================

class TestProfileView(APITestCase):
    """Tests for user profile GET/POST."""

    def setUp(self):
        self.url = reverse('profile')
        self.org = Organisations.objects.create(name='Profile Org', website='https://profile.com')
        self.user = User.objects.create_user(
            username='profileuser',
            email='profile@example.com',
            password='TestPass123!',
            first_name='Profile',
            last_name='User',
            phone='1111111111',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)

    def test_get_profile(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['email'], 'profile@example.com')
        self.assertEqual(response.data['first_name'], 'Profile')

    def test_update_profile(self):
        response = self.client.post(self.url, {
            'first_name': 'Updated',
            'last_name': 'Name',
            'phone': '2222222222',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Updated')

    def test_update_email_unique(self):
        User.objects.create_user(
            username='other', email='taken@example.com', password='Pass123!',
            organisation=self.org, is_active=True,
        )
        response = self.client.post(self.url, {'email': 'taken@example.com'})
        self.assertEqual(response.status_code, 400)

    def test_update_phone_unique(self):
        User.objects.create_user(
            username='other2', email='other2@example.com', password='Pass123!',
            phone='9999999999', organisation=self.org, is_active=True,
        )
        response = self.client.post(self.url, {'phone': '9999999999'})
        self.assertEqual(response.status_code, 400)

    def test_profile_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_update_partial_fields(self):
        response = self.client.post(self.url, {'first_name': 'OnlyFirst'})
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'OnlyFirst')
        self.assertEqual(self.user.last_name, 'User')  # Unchanged


# =============================================================================
# UpdatePasswordView
# =============================================================================

class TestUpdatePasswordView(APITestCase):
    """Tests for password change endpoint."""

    def setUp(self):
        self.url = reverse('update-password')
        self.org = Organisations.objects.create(name='PW Org', website='https://pw.com')
        self.user = User.objects.create_user(
            username='pwuser',
            email='pw@example.com',
            password='OldPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)

    @patch('Users.views.log_action')
    def test_change_password_success(self, mock_log):
        response = self.client.post(self.url, {
            'old_password': 'OldPass123!',
            'new_password': 'NewPass456!',
            'new_password_copy': 'NewPass456!',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewPass456!'))

    def test_wrong_old_password(self):
        response = self.client.post(self.url, {
            'old_password': 'WrongOld!',
            'new_password': 'NewPass456!',
            'new_password_copy': 'NewPass456!',
        })
        self.assertEqual(response.status_code, 400)

    def test_new_passwords_mismatch(self):
        response = self.client.post(self.url, {
            'old_password': 'OldPass123!',
            'new_password': 'NewPass456!',
            'new_password_copy': 'DifferentPass!',
        })
        self.assertEqual(response.status_code, 400)

    def test_change_password_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url, {
            'old_password': 'OldPass123!',
            'new_password': 'NewPass456!',
            'new_password_copy': 'NewPass456!',
        })
        self.assertIn(response.status_code, (401, 403))


# =============================================================================
# ForgetPasswordView
# =============================================================================

class TestForgetPasswordView(APITestCase):
    """Tests for password reset request endpoint."""

    def setUp(self):
        self.url = reverse('forget-password')
        self.org = Organisations.objects.create(name='Forget Org', website='https://forget.com')
        self.user = User.objects.create_user(
            username='forgetuser',
            email='forget@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )

    @patch('Users.views.send_reset_password_link')
    def test_forget_password_sends_email(self, mock_send):
        response = self.client.post(self.url, {'email': 'forget@example.com'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send.assert_called_once()

    def test_forget_password_unknown_email(self):
        # Returns 200 with a generic message — never confirms whether
        # the email exists. Prior behaviour (400 "Email address not
        # found") leaked account enumeration to unauthenticated
        # attackers (BE-P1-03, audit 2026-09-05). Rate-limit slows
        # enumeration but the constant-response is what actually
        # closes the oracle.
        response = self.client.post(self.url, {'email': 'unknown@example.com'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Same body shape as the success case so response length + JSON
        # keys can't be used as a side-channel oracle either.
        self.assertIn('message', response.data)

    def test_forget_password_missing_email(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


# =============================================================================
# SetPasswordView
# =============================================================================

class TestSetPasswordView(APITestCase):
    """Tests for password reset (with token) endpoint."""

    def setUp(self):
        self.org = Organisations.objects.create(name='SetPW Org', website='https://setpw.com')
        self.user = User.objects.create_user(
            username='setpwuser',
            email='setpw@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.token_generator = PasswordResetTokenGenerator()
        self.uidb64 = urlsafe_base64_encode(str(self.user.pk).encode('utf-8'))
        self.token = self.token_generator.make_token(self.user)
        self.url = reverse('set-password', kwargs={
            'uidb64': self.uidb64,
            'token': self.token,
        })

    @patch('Users.views.log_action')
    def test_set_password_valid_token(self, mock_log):
        response = self.client.post(self.url, {
            'new_password': 'BrandNew123!',
            'new_password_confirm': 'BrandNew123!',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('BrandNew123!'))

    def test_set_password_invalid_token(self):
        url = reverse('set-password', kwargs={
            'uidb64': self.uidb64,
            'token': 'invalid-token',
        })
        response = self.client.post(url, {
            'new_password': 'BrandNew123!',
            'new_password_confirm': 'BrandNew123!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_password_mismatch(self):
        # Mismatch is a client error, not a 500 (2026-10-20 review).
        response = self.client.post(self.url, {
            'new_password': 'BrandNew123!',
            'new_password_confirm': 'Different123!',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_password_missing_fields(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_set_password_rejects_weak_password(self):
        # AUTH_PASSWORD_VALIDATORS apply on reset, as on register.
        response = self.client.post(self.url, {
            'new_password': '123',
            'new_password_confirm': '123',
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertFalse(self.user.check_password('123'))


# =============================================================================
# InvitationsetPasswordView
# =============================================================================

class TestInvitationSetPasswordView(APITestCase):
    """Tests for invitation password-set endpoint.

    The view was hardened 2026-08-30 (account-takeover fix): it now
    decodes ``user_id`` from the signed invitation JWT server-side
    instead of trusting a body-supplied ``user_id``. These tests
    provide a real JWT — same shape as
    ``Utils.email_utils.send_invitation_link`` encodes into
    invitation emails.
    """

    def setUp(self):
        from django.conf import settings as django_settings
        import jwt

        self.url = reverse('accept-password')
        self.org = Organisations.objects.create(name='Invite Org', website='https://invite.com')
        self.user = User.objects.create_user(
            username='inviteuser',
            email='invite@example.com',
            password='TempPass123!',
            organisation=self.org,
            role='user',
            is_active=True,
        )
        # The token send_invitation_link puts in the email.
        from Utils.email_utils import make_invitation_token
        self.token = make_invitation_token(self.user)

    @patch('Users.views.log_action')
    def test_set_invitation_password_success(self, mock_log):
        response = self.client.post(self.url, {
            'token': self.token,
            'password': 'NewInvite123!',
            'password_confirmation': 'NewInvite123!',
        })
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewInvite123!'))

    def test_set_invitation_password_user_not_found(self):
        """Valid JWT for a user who no longer exists → 404."""
        from django.conf import settings as django_settings
        import jwt
        import time
        stale_token = jwt.encode(
            {'user': 99999, 'organisation': self.org.id, 'role': 'user', 'exp': int(time.time()) + 600},
            django_settings.SECRET_KEY,
            algorithm='HS256',
        )
        response = self.client.post(self.url, {
            'token': stale_token,
            'password': 'NewInvite123!',
            'password_confirmation': 'NewInvite123!',
        })
        self.assertEqual(response.status_code, 404)

    @patch('Users.views.log_action')
    def test_invitation_link_works_once(self, mock_log):
        """An old invitation email must not reset the password again."""
        body = {'token': self.token, 'password': 'NewInvite123!', 'password_confirmation': 'NewInvite123!'}
        self.assertEqual(self.client.post(self.url, body).status_code, 200)
        again = dict(body, password='Attacker123!', password_confirmation='Attacker123!')
        self.assertEqual(self.client.post(self.url, again).status_code, 401)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NewInvite123!'))
        # The accept endpoint refuses the used link too.
        self.assertEqual(self.client.get(reverse('accept-invitation', args=[self.token])).status_code, 400)

    def test_invitation_link_expires(self):
        from unittest.mock import patch as _patch
        from Utils.email_utils import make_invitation_token
        with _patch('Utils.email_utils.INVITATION_TTL_DAYS', -1):
            expired = make_invitation_token(self.user)
        response = self.client.post(self.url, {
            'token': expired, 'password': 'NewInvite123!', 'password_confirmation': 'NewInvite123!'})
        self.assertEqual(response.status_code, 401)
        self.assertIn('expired', response.json()['error'])

    def test_token_without_expiry_is_refused(self):
        """Links sent before the fix carried no exp: they must not be accepted."""
        from django.conf import settings as django_settings
        import jwt
        legacy = jwt.encode({'user': self.user.id, 'organisation': self.org.id, 'role': 'user'},
                            django_settings.SECRET_KEY, algorithm='HS256')
        response = self.client.post(self.url, {
            'token': legacy, 'password': 'NewInvite123!', 'password_confirmation': 'NewInvite123!'})
        self.assertEqual(response.status_code, 401)

    def test_set_invitation_password_mismatch(self):
        response = self.client.post(self.url, {
            'token': self.token,
            'password': 'NewInvite123!',
            'password_confirmation': 'Different123!',
        })
        self.assertEqual(response.status_code, 400)

    def test_set_invitation_password_invalid_token(self):
        """Bogus JWT → 401 (was the account-takeover attack vector)."""
        response = self.client.post(self.url, {
            'token': 'not-a-real-jwt',
            'password': 'NewInvite123!',
            'password_confirmation': 'NewInvite123!',
        })
        self.assertEqual(response.status_code, 401)

    def test_set_invitation_password_body_user_id_is_ignored(self):
        """Body-supplied user_id must NOT let a caller take over another
        user — the whole point of the hardening. Sending user_id
        without a token should hit the 'token required' 400."""
        response = self.client.post(self.url, {
            'user_id': self.user.pk,
            'password': 'NewInvite123!',
            'password_confirmation': 'NewInvite123!',
        })
        self.assertEqual(response.status_code, 400)


# =============================================================================
# ProfileAvatarView
# =============================================================================

class TestProfileAvatarView(APITestCase):
    """Tests for avatar upload endpoint."""

    def setUp(self):
        self.url = reverse('upload-profile-avatar')
        self.org = Organisations.objects.create(name='Avatar Org', website='https://avatar.com')
        self.user = User.objects.create_user(
            username='avataruser',
            email='avatar@example.com',
            password='TestPass123!',
            organisation=self.org,
            role='admin',
            is_active=True,
        )
        self.client.force_authenticate(user=self.user)

    def _image(self, size=(300, 200), fmt='JPEG', name='photo.jpg'):
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new('RGB', size, (200, 40, 40)).save(buf, format=fmt)
        return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')

    def test_upload_stores_small_png_in_db(self):
        response = self.client.put(self.url, {'avatar': self._image()}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(response.data['avatar'], f'/auth/avatar/{self.user.avatar_key}')
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(bytes(self.user.avatar_png)))
        self.assertEqual((img.format, img.size), ('PNG', (128, 85)))

    def test_gif_accepted(self):
        response = self.client.put(self.url, {'avatar': self._image(fmt='GIF', name='a.gif')}, format='multipart')
        self.assertEqual(response.status_code, 200)

    def test_non_image_rejected(self):
        fake = SimpleUploadedFile('test.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, content_type='image/png')
        response = self.client.put(self.url, {'avatar': fake}, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.avatar_key, '')

    def test_new_upload_changes_key(self):
        self.client.put(self.url, {'avatar': self._image()}, format='multipart')
        self.user.refresh_from_db()
        first = self.user.avatar_key
        self.client.put(self.url, {'avatar': self._image()}, format='multipart')
        self.user.refresh_from_db()
        self.assertNotEqual(first, self.user.avatar_key)

    def test_avatar_served_without_auth(self):
        self.client.put(self.url, {'avatar': self._image()}, format='multipart')
        self.user.refresh_from_db()
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('avatar', kwargs={'key': self.user.avatar_key}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('immutable', response['Cache-Control'])
        self.assertEqual(response.content, bytes(self.user.avatar_png))

    def test_unknown_key_404(self):
        response = self.client.get(reverse('avatar', kwargs={'key': 'deadbeef' * 4}))
        self.assertEqual(response.status_code, 404)

    def test_delete_removes_avatar(self):
        self.client.put(self.url, {'avatar': self._image()}, format='multipart')
        self.user.refresh_from_db()
        key = self.user.avatar_key
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.avatar_png)
        self.assertEqual(self.client.get(reverse('avatar', kwargs={'key': key})).status_code, 404)
        self.assertIsNone(self.client.get(reverse('profile')).data['avatar'])

    def test_upload_avatar_no_data(self):
        response = self.client.put(self.url, {}, format='multipart')
        self.assertEqual(response.status_code, 400)


class InvitationEmailTest(APITestCase):
    """The invitation said "Hello ," and "Join your Team on Serops!", without
    the organisation or who invited (journey suite, E1-E3)."""

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', EMAIL_HOST='')
    def test_names_the_organisation_and_the_inviter(self):
        from django.core import mail
        from Utils.email_utils import send_invitation_link
        org = Organisations.objects.create(name='Acme')
        admin = User.objects.create_user(username='ada', email='ada@acme.test', password='x',
                                         first_name='Ada', last_name='Admin', organisation=org)
        invitee = User.objects.create_user(username='bob', email='bob@acme.test', password='x', organisation=org)
        with patch('Utils.email_utils._get_connection_and_from', return_value=(None, 'serops@acme.test')):
            send_invitation_link(invitee, invited_by=admin)
        message = mail.outbox[-1]
        self.assertEqual(message.subject, "You're invited to join Acme on SerOps")
        self.assertIn('Ada Admin has invited you', message.body)
        self.assertIn('<strong>Acme</strong>', message.body)
        self.assertIn('Hello,', message.body)
