from unittest import mock
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from Organisations.models import Organisations
from rest_framework.authtoken.models import Token
from Users.models import User


class OrganisationViewsTest(APITestCase):
    def setUp(self):
        # Create organisation
        self.organisation = Organisations.objects.create(
            name="Test Org",
            website="https://testorg.com"
        )

        # Create user with organisation
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            email='test@example.com',
            first_name='Test',
            last_name='User',
            organisation=self.organisation,
            # The team and member endpoints are guarded by team.manage (admin), and
            # User.role defaults to 'viewer'. Without this every request to
            # them returns 403.
            role='admin',
        )

        # Auth.
        #
        # Was a DRF `Token` + Authorization header. That cannot authenticate
        # here: Knox's OptimizedTokenAuthentication runs first, uses the same
        # "Token" keyword, and RAISES AuthenticationFailed on a key it does
        # not recognise — DRF stops at the first authenticator that raises, so
        # the `TokenAuthentication` entry in DEFAULT_AUTHENTICATION_CLASSES
        # (commented "Fallback for old tokens") is never reached. Every
        # request came back 401.
        #
        # force_authenticate targets what these tests are actually about —
        # the view's behaviour and permissions — without coupling them to
        # whichever token backend is current.
        self.client.force_authenticate(user=self.user)

        # URLs
        self.organisation_info_url = reverse('organisation-info')
        self.organisation_team_url = reverse('organisation-team')

        # Create another user (team member)
        self.team_member = User.objects.create_user(
            username='teammember',
            email='team@example.com',
            password='teampass',
            organisation=self.organisation
        )
        self.organisation_member_url = reverse('organisation-member', kwargs={'id': self.team_member.id})

    def test_organisation_info_get(self):
        response = self.client.get(self.organisation_info_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['name'], 'Test Org')

    # Updating an organisation moved from `POST /organisation/info/` to
    # `PUT /organisation/update/<id>/`. The info endpoint is GET-only now, so
    # the old POSTs returned 405. Validation failures are DRF serializer
    # errors keyed by field, not a flat {'error': ...} body.

    def test_organisation_update_valid_data(self):
        url = reverse('organisation-update', kwargs={'id': self.organisation.id})
        response = self.client.put(
            url, {'name': 'Updated Organisation', 'website': 'https://updated.com'},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.organisation.refresh_from_db()
        self.assertEqual(self.organisation.name, 'Updated Organisation')

    def test_organisation_update_rejects_blank_name(self):
        url = reverse('organisation-update', kwargs={'id': self.organisation.id})
        response = self.client.put(url, {'name': ''}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('name', response.data)

    def test_organisation_update_missing_org_is_404(self):
        url = reverse('organisation-update', kwargs={'id': self.organisation.id + 9999})
        response = self.client.put(url, {'name': 'Nope'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_organisation_info_is_get_only(self):
        """Guards the move: a POST here must not silently start working
        again without someone deciding to reinstate it."""
        response = self.client.post(
            self.organisation_info_url, {'name': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_organisation_team_get(self):
        response = self.client.get(self.organisation_team_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('users', response.data)
        self.assertIn('total_pages', response.data)

    def test_organisation_team_post_basic(self):
        data = {
            'user': {
                'email': 'newmember@example.com',
                'first_name': 'New',
                'last_name': 'Member',
                'phone': '1234567890',
                'role': 'user',
                'username': 'newmember'
            }
        }
        response = self.client.post(self.organisation_team_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)

    def test_organisation_team_post_missing_user_data(self):
        data = {}  # No 'user' key
        response = self.client.post(self.organisation_team_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_organisation_team_post_invalid_email(self):
        data = {
            'user': {
                'email': 'invalid_email',
                'first_name': 'New',
                'last_name': 'Member',
                'phone': '1234567890',  # Added phone field
                'role': 'user',
                'username': 'newmember'
            }
        }
        response = self.client.post(self.organisation_team_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["email"], "Invalid email format")

    def test_organisation_team_post_duplicate_email(self):
        data = {
            'user': {
                'email': 'team@example.com',  # Already used
                'first_name': 'New',
                'last_name': 'Member',
                'phone': '12345678',
                'role': 'user',
                'username': 'newmember'
            }
        }
        response = self.client.post(self.organisation_team_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_organisation_team_post_requires_email(self):
        """Email is the only required field for an invitation.

        This previously asserted that an invite WITHOUT first_name/last_name
        was a 400. It is not, and should not be: the documented payload is
        `{"user": {"email": ..., "role": ...}}` — names are collected when the
        invitee accepts, because the inviter usually does not know them. The
        real required field is the address, so that is what is asserted.
        """
        response = self.client.post(
            self.organisation_team_url, {'user': {'role': 'user'}}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_organisation_team_post_accepts_email_only(self):
        response = self.client.post(
            self.organisation_team_url,
            {'user': {'email': 'nameless@test.com', 'role': 'user'}},
            format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    """   @mock.patch('Utils.email_utils.send_invitation_link')
    def test_organisation_team_post_invitation_sent(self, mock_send_invitation):
        data = {
            'user': {
                'email': 'newmember@test.com',
                'first_name': 'New',
                'last_name': 'Member',
                'phone': '1234567890',
                'role': 'user',
                'username': 'newmember'
            }
        }
        response = self.client.post(self.organisation_team_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send_invitation.assert_called_once()
        user = User.objects.get(email='newmember@test.com')
        mock_send_invitation.assert_called_with(user) """

    def test_organisation_member_get(self):
        response = self.client.get(self.organisation_member_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('user', response.data)

    def test_organisation_member_put(self):
        data = {
            'first_name': 'Updated',
            'last_name': 'Member',
            'email': 'team@example.com',
            'phone': '9876543210',
            'role': 'admin'
        }
        response = self.client.put(self.organisation_member_url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('message', response.data)

    def test_organisation_member_delete(self):
        response = self.client.delete(self.organisation_member_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('success', response.data)
        class RegisterViewTest(APITestCase):
            def setUp(self):
                self.url = reverse('register')
                self.valid_payload = {
                    'user': {
                        'email': 'test@example.com',
                        'password': 'testpass123',
                        'password_confirmation': 'testpass123',
                        'first_name': 'Test',
                        'last_name': 'User',
                        'phone': '1234567890'
                    },
                    'organisation': {
                        'name': 'Test Organisation',
                        'website': 'https://test.com'
                    }
                }

            def test_successful_registration(self):
                """Test successful user registration with valid data"""
                response = self.client.post(self.url, self.valid_payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                self.assertTrue(User.objects.filter(email='test@example.com').exists())
                self.assertTrue(Organisations.objects.filter(name='Test Organisation').exists())

            def test_registration_without_user_data(self):
                """Test registration attempt without user data"""
                payload = {'organisation': self.valid_payload['organisation']}
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'Both user and organisation data are required')

            def test_registration_without_organisation_data(self):
                """Test registration attempt without organisation data"""
                payload = {'user': self.valid_payload['user']}
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'Both user and organisation data are required')

            def test_registration_with_password_mismatch(self):
                """Test registration with mismatched passwords"""
                payload = self.valid_payload.copy()
                payload['user']['password_confirmation'] = 'wrongpassword'
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'Passwords do not match')

            def test_registration_with_existing_email(self):
                """Test registration attempt with an existing email"""
                # First create a user
                self.client.post(self.url, self.valid_payload, format='json')
                
                # Try to register again with the same email
                response = self.client.post(self.url, self.valid_payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'Email already exists')

            @mock.patch('Users.views.send_activation_link')
            def test_registration_with_failed_email_sending(self, mock_send_email):
                """Test registration when email sending fails"""
                mock_send_email.side_effect = Exception("Email sending failed")
                response = self.client.post(self.url, self.valid_payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_201_CREATED)
                mock_send_email.assert_called_once()

            def test_registration_with_invalid_user_data(self):
                """Test registration with invalid user data"""
                payload = self.valid_payload.copy()
                payload['user']['email'] = 'invalid-email'  # Invalid email format
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            def test_registration_with_invalid_organisation_data(self):
                """Test registration with invalid organisation data"""
                payload = self.valid_payload.copy()
                payload['organisation']['website'] = 'invalid-url'  # Invalid URL format
                response = self.client.post(self.url, payload, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

            def test_registration_with_empty_payload(self):
                """Test registration with empty payload"""
                response = self.client.post(self.url, {}, format='json')
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data['error'], 'Both user and organisation data are required')
                def test_organisation_info_post_same_name(self):
                    """Test updating organization with the same name should succeed"""
                    data = {
                        'name': self.organisation.name,
                        'website': 'https://newwebsite.com'
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertEqual(response.data['organisation']['name'], self.organisation.name)

                def test_organisation_info_post_invalid_website(self):
                    """Test updating organization with invalid website format"""
                    data = {
                        'name': 'Valid Name',
                        'website': 'invalid-website'  # Invalid website format
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

                def test_organisation_info_post_empty_fields(self):
                    """Test updating organization with empty fields"""
                    data = {
                        'name': '',
                        'website': ''
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn('error', response.data)

                def test_organisation_info_post_missing_payload(self):
                    """Test updating organization with missing payload"""
                    response = self.client.post(self.organisation_info_url, {}, format='json')
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn('error', response.data)

                def test_organisation_info_post_partial_data(self):
                    """Test updating organization with partial data"""
                    data = {
                        'name': 'New Name'
                        # Missing website field
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertIn('error', response.data)

                def test_organisation_info_post_different_org(self):
                    """Test updating organization when another org exists with different name"""
                    # Create another organization first
                    Organisations.objects.create(
                        name="Other Org",
                        website="https://otherorg.com"
                    )
                    
                    data = {
                        'name': 'Completely New Name',
                        'website': 'https://newsite.com'
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertEqual(response.data['organisation']['name'], 'Completely New Name')

                def test_organisation_info_post_with_spaces(self):
                    """Test updating organization with name containing leading/trailing spaces"""
                    data = {
                        'name': '  Spaced Name  ',
                        'website': 'https://valid.com'
                    }
                    response = self.client.post(self.organisation_info_url, data, format='json')
                    self.assertEqual(response.status_code, status.HTTP_200_OK)
                    self.assertEqual(response.data['organisation']['name'].strip(), 'Spaced Name')