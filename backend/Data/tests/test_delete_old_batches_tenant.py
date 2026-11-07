"""
Deleting old batches deletes this organisation's only. The query had no
organisation filter: any org admin deleted every tenant's old batches
(external review, 2026-11).
"""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Users.models import User


class DeleteOldBatchesTenantTest(APITestCase):
    def setUp(self):
        self.org_a = Organisations.objects.create(name='Org A')
        self.org_b = Organisations.objects.create(name='Org B')
        self.admin_a = User.objects.create_user(username='a', email='a@example.com', password='TestPass123!',
                                                organisation=self.org_a, role='admin', is_active=True)
        for org, bid in ((self.org_a, 'a-old'), (self.org_b, 'b-old')):
            b = AIAnalyzedBatch.objects.create(batch_id=bid, organisation=org, timestamp=timezone.now(), data={})
            AIAnalyzedBatch.objects.filter(pk=b.pk).update(created_at=timezone.now() - timedelta(days=90))

    def test_an_admin_deletes_only_their_organisations_batches(self):
        self.client.force_authenticate(user=self.admin_a)
        response = self.client.delete('/api/data/delete-old-batches/?days=30')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['deleted_batches'], 1)
        self.assertEqual(list(AIAnalyzedBatch.objects.values_list('batch_id', flat=True)), ['b-old'])
