"""Login, profile and demo sign-in send one user shape: the UI reads
``organisation`` as a name (an id crashed the sidebar after a profile save)
and shows controls from ``permissions``."""
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User


class UserPayloadShapeTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.user = User.objects.create_user(username='u', email='u@acme.test', password='Pass-word-123',
                                             organisation=self.org, role='user', is_active=True)

    def check(self, data, name):
        self.assertEqual((data['organisation'], data['organisation_id'], data['role']), ('Acme', self.org.id, 'user'), name)
        self.assertIn('project.write', data['permissions'], name)

    def test_login_and_profile(self):
        self.check(self.client.post(reverse('login'), {'email': 'u@acme.test', 'password': 'Pass-word-123'},
                                    format='json').data['user'], 'login')
        self.client.force_authenticate(user=self.user)
        self.check(self.client.get('/api/auth/profile').data, 'profile GET')
        self.check(self.client.post('/api/auth/profile', {'first_name': 'Ada'}, format='json').data, 'profile update')

    def test_demo_login(self):
        Organisations.objects.filter(pk=self.org.pk).update(is_demo=True)
        User.objects.filter(pk=self.user.pk).update(is_demo=True)
        response = self.client.post('/api/auth/demo-login')
        self.assertEqual(response.status_code, 200, response.data)
        user = response.data['user']
        self.check(user, 'demo-login')
        self.assertEqual((user['is_demo'], user['organisation_name']), (True, 'Acme'))
