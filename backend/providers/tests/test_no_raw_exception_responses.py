"""
A generic ``except Exception`` handler must not hand the exception text to
the caller (CodeQL py/stack-trace-exposure): it can carry connection
strings, hostnames or tokens. The response keeps its status and a fixed
message; the traceback goes to the backend log.
"""
import json
from unittest import mock

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Users.models import User

SECRET = 'postgres://user:s3cret@db/x'


class ApiResponsesHideExceptionTextTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Raw errors org')
        cls.admin = User.objects.create_user(
            username='raw-admin', email='raw-admin@a.example', password='x',
            organisation=cls.org, role='admin', is_active=True,
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def assertHidden(self, response, status_code):
        self.assertEqual(response.status_code, status_code)
        body = response.content.decode()
        self.assertNotIn('s3cret', body)
        self.assertNotIn(SECRET, body)
        self.assertNotIn('details', json.loads(body))

    def test_issues_list(self):
        with mock.patch('Data.views.IssueListView.filter_by_org', side_effect=Exception(SECRET)), \
                self.assertLogs('Data.views', level='ERROR') as logs:
            response = self.client.get('/api/data/issues/')
        self.assertHidden(response, 500)
        self.assertEqual(response.json()['error'], 'Failed to retrieve issues')
        self.assertIn('Traceback', '\n'.join(logs.output))  # logged with its traceback

    def test_batch_detail(self):
        with mock.patch('Data.views.scope_request', side_effect=Exception(SECRET)):
            response = self.client.get('/api/data/batches/b-1/')
        self.assertHidden(response, 400)

    def test_provider_connection_test(self):
        with mock.patch('providers.scm_providers.get_provider', side_effect=Exception(SECRET)):
            response = self.client.post('/api/providers/integrations/test/', {
                'provider_type': 'gitlab', 'access_token': 't'}, format='json')
        self.assertHidden(response, 400)
        self.assertEqual(response.json()['message'], 'Connection test failed. The backend log has the details.')


class WebhookResponseHidesExceptionTextTest(SimpleTestCase):
    def test_gitlab_webhook(self):
        from providers.gitlab_webhook import GitLabCICDWebhookHandler

        request = mock.Mock(body=b'{}', data={})
        with mock.patch.object(GitLabCICDWebhookHandler, '_resolve_binding', side_effect=Exception(SECRET)), \
                self.assertLogs('providers.gitlab_webhook', level='ERROR'):
            response = GitLabCICDWebhookHandler().post(request)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data, {'error': 'Webhook processing failed'})
