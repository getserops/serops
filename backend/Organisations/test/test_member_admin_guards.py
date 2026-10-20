"""
Guards on what an org admin can do to members (2026-10-20 review).
"""
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User


class MemberAdminGuardsTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Guard Org')
        self.other_org = Organisations.objects.create(name='Other Guard Org')
        self.admin = User.objects.create_user(username='a1', email='a1@guard.example.com', password='Xx-12345678',
                                              organisation=self.org, role='admin', is_active=True)
        self.admin2 = User.objects.create_user(username='a2', email='a2@guard.example.com', password='Xx-12345678',
                                               organisation=self.org, role='admin', is_active=True)
        self.client = APIClient(raise_request_exception=False)
        self.client.force_authenticate(user=self.admin)

    def put(self, user, body):
        return self.client.put(f'/api/organisation/member/{user.id}/', body, format='json')

    def test_admin_cannot_change_a_members_email(self):
        r = self.put(self.admin2, {'email': 'attacker@evil.example.com', 'first_name': 'Bea'})
        self.assertEqual(r.status_code, 200)
        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.email, 'a2@guard.example.com')
        self.assertEqual(self.admin2.first_name, 'Bea')

    def test_invalid_role_is_a_400(self):
        r = self.put(self.admin2, {'role': 'superadmin'})
        self.assertEqual(r.status_code, 400)
        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.role, 'admin')

    def test_cannot_demote_the_last_admin(self):
        self.assertEqual(self.put(self.admin2, {'role': 'viewer'}).status_code, 200)
        self.assertEqual(self.put(self.admin, {'role': 'viewer'}).status_code, 400)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, 'admin')

    def test_cannot_delete_the_last_admin(self):
        self.assertEqual(self.client.delete(f'/api/organisation/member/{self.admin2.id}/').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/organisation/member/{self.admin.id}/').status_code, 400)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_can_still_demote_when_another_admin_remains(self):
        self.assertEqual(self.put(self.admin2, {'role': 'user'}).status_code, 200)

    def test_invite_cannot_pull_in_another_orgs_user(self):
        outsider = User.objects.create_user(username='o', email='outsider@guard.example.com', password='Xx-12345678',
                                            organisation=self.other_org, role='admin', is_active=True)
        r = self.client.post('/api/organisation/team/', {'user': {'email': 'outsider@guard.example.com', 'role': 'viewer'}},
                             format='json')
        self.assertGreaterEqual(r.status_code, 400)
        outsider.refresh_from_db()
        self.assertEqual(outsider.organisation_id, self.other_org.id)
        self.assertEqual(outsider.role, 'admin')
