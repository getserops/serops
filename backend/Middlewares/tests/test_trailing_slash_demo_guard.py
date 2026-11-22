"""A request re-dispatched by the trailing-slash fallback is still refused for
the demo user (audit 2026-11-20, item 17). The fallback calls the view
directly, which skips process_view hooks; the demo guard must not depend on
them."""
from knox.models import AuthToken
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User


class TrailingSlashDemoGuardTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme Demo', is_demo=True)
        self.demo = User.objects.create_user(username='slashdemo', email='slashdemo@example.com', password='TestPass123!',
                                             organisation=self.org, role='admin', is_active=True, is_demo=True,
                                             first_name='Before')
        self.member = User.objects.create_user(username='slashmember', email='slashmember@example.com',
                                               password='TestPass123!', organisation=Organisations.objects.create(name='Real'),
                                               role='admin', is_active=True)

    def post_profile(self, user, path):
        _, token = AuthToken.objects.create(user=user)
        return self.client.post(path, {'first_name': 'Changed'}, format='json', HTTP_AUTHORIZATION=f'Token {token}')

    def test_demo_write_through_the_fallback_is_refused(self):
        # /api/auth/profile is declared without a slash: the slashed form only
        # reaches the view through the fallback.
        response = self.post_profile(self.demo, '/api/auth/profile/')
        self.assertEqual(response.status_code, 403)
        self.demo.refresh_from_db()
        self.assertEqual(self.demo.first_name, 'Before')

    def test_the_fallback_still_works_for_a_real_user(self):
        response = self.post_profile(self.member, '/api/auth/profile/')
        self.assertEqual(response.status_code, 200, response.content)
        self.member.refresh_from_db()
        self.assertEqual(self.member.first_name, 'Changed')
