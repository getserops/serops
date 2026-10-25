"""
Settings → Integrations builds its rows and their Edit dialog from the list
endpoint. Without scope and cluster there, every row read "unscoped", the
Environment typed at creation looked lost, and saving the dialog cleared the
stored scope and cluster (journey suite, B2).
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from Organisations.models import Organisations


class ObservabilityListScopeTest(APITestCase):
    def setUp(self):
        org = Organisations.objects.create(name='List Org')
        admin = get_user_model().objects.create_user(
            username='list-admin', email='la@test.com', password='Test123!',
            organisation=org, role='admin', is_active=True)
        self.client.force_authenticate(admin)
        self.url = '/api/integrations/observability/'

    def test_list_has_scope_and_cluster(self):
        response = self.client.post(self.url, {
            'provider': 'prometheus', 'display_name': 'Prom', 'capabilities': ['metrics'],
            'host': 'http://prometheus:9090', 'scope': {'environment': 'production'},
        }, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        rows = self.client.get(self.url).data
        rows = rows['results'] if isinstance(rows, dict) else rows
        prom = next(r for r in rows if r['provider'] == 'prometheus')
        self.assertEqual(prom['scope']['environment'], 'production')
        self.assertIn('cluster', prom)
