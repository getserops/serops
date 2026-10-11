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
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

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
        # View raises Django ValidationError (not DRF's), which propagates as exception
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.client.post(self.url, {
                'new_password': 'BrandNew123!',
                'new_password_confirm': 'Different123!',
            })

    def test_set_password_missing_fields(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.client.post(self.url, {})


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
        # Real invitation JWT — mirrors send_invitation_link's payload.
        self.token = jwt.encode(
            {'user': self.user.id, 'organisation': self.org.id, 'role': self.user.role},
            django_settings.SECRET_KEY,
            algorithm='HS256',
        )

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
        stale_token = jwt.encode(
            {'user': 99999, 'organisation': self.org.id, 'role': 'user'},
            django_settings.SECRET_KEY,
            algorithm='HS256',
        )
        response = self.client.post(self.url, {
            'token': stale_token,
            'password': 'NewInvite123!',
            'password_confirmation': 'NewInvite123!',
        })
        self.assertEqual(response.status_code, 404)

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

    @patch('builtins.open', mock_open())
    def test_upload_avatar_png(self):
        avatar = SimpleUploadedFile('test.png', b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, content_type='image/png')
        response = self.client.put(self.url, {'avatar': avatar}, format='multipart')
        self.assertEqual(response.status_code, 200)

    @patch('builtins.open', mock_open())
    def test_upload_avatar_jpeg(self):
        avatar = SimpleUploadedFile('photo.jpeg', b'\xff\xd8\xff\xe0' + b'\x00' * 100, content_type='image/jpeg')
        response = self.client.put(self.url, {'avatar': avatar}, format='multipart')
        self.assertEqual(response.status_code, 200)

    @patch('builtins.open', mock_open())
    def test_upload_avatar_invalid_format(self):
        avatar = SimpleUploadedFile('anim.gif', b'GIF89a' + b'\x00' * 100, content_type='image/gif')
        response = self.client.put(self.url, {'avatar': avatar}, format='multipart')
        self.assertEqual(response.status_code, 400)

    def test_upload_avatar_no_data(self):
        response = self.client.put(self.url, {}, format='multipart')
        self.assertEqual(response.status_code, 400)
