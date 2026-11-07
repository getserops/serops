"""
The demo stays read-only whatever form of the token header is sent. Knox
matches its 'Token' prefix without regard to case; the middleware matched
'Token ' exactly, so 'token <value>' skipped the guard while Knox still
signed the visitor in, as the demo's admin (external review, 2026-11).
"""
from datetime import timedelta

from django.utils import timezone
from knox.models import AuthToken
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Users.models import User

URL = '/api/data/delete-old-batches/'


class DemoGuardTokenFormsTest(APITestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme Cloud')
        self.demo = User.objects.create_user(username='demo', email='demo@example.com', password='TestPass123!',
                                             organisation=self.org, role='admin', is_active=True, is_demo=True)
        self.admin = User.objects.create_user(username='adm', email='adm@example.com', password='TestPass123!',
                                              organisation=self.org, role='admin', is_active=True)
        old = AIAnalyzedBatch.objects.create(batch_id='old', organisation=self.org, timestamp=timezone.now(), data={})
        AIAnalyzedBatch.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=90))

    def call(self, user, prefix, method='delete'):
        _, token = AuthToken.objects.create(user=user)
        return getattr(self.client, method)(URL, HTTP_AUTHORIZATION=f'{prefix} {token}')

    def test_every_case_of_the_prefix_is_refused_for_the_demo(self):
        for prefix in ('Token', 'token', 'TOKEN', 'tOkEn'):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.call(self.demo, prefix).status_code, 403)
        self.assertTrue(AIAnalyzedBatch.objects.filter(batch_id='old').exists())

    def test_the_demo_can_still_read(self):
        _, token = AuthToken.objects.create(user=self.demo)
        response = self.client.get('/api/data/issues/', HTTP_AUTHORIZATION=f'token {token}')
        self.assertEqual(response.status_code, 200)

    def test_a_real_admin_is_not_affected(self):
        self.assertEqual(self.call(self.admin, 'token').status_code, 200)
        self.assertFalse(AIAnalyzedBatch.objects.filter(batch_id='old').exists())
