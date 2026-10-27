"""
Follow-ups to the GitLab project check fix (1.2.8): the legacy project
registration endpoint had the same SSRF and leaked another organisation's
webhook secret; GitLab replies were echoed elsewhere; integration URLs and
notification senders could reach cloud metadata or follow redirects.
"""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import GitlabProject, ProviderIntegration
from Users.models import User


def _reply(status, body):
    r = mock.Mock(status_code=status, text=str(body))
    r.json.return_value = body
    return r


class ProjectRegistrationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Caller org')
        cls.other = Organisations.objects.create(name='Other org')
        cls.user = User.objects.create_user(username='dev', email='dev@a.example', password='x',
                                            organisation=cls.org, role='user', is_active=True)
        cls.admin = User.objects.create_user(username='adm', email='adm@a.example', password='x',
                                             organisation=cls.org, role='admin', is_active=True)
        GitlabProject.objects.create(gitlab_url='https://gitlab.other.example', username='o', name='theirs',
                                     project_id='123', access_token='t', organisation=cls.other)
        integration = ProviderIntegration.objects.create(name='gl', provider_type='gitlab', organisation=cls.other)
        service = ProjectService.objects.create(project=Project.objects.create(name='p', organisation=cls.other),
                                                name='svc')
        cls.binding = CICDBinding.objects.create(project_service=service, integration=integration,
                                                 pipeline_id='123', webhook_secret='OTHER-ORG-SECRET')

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **body):
        return self.client.post('/api/providers/', {'access_token': 'tok', **body}, format='json')

    @mock.patch('providers.views.requests.get')
    def test_metadata_and_path_escapes_are_refused(self, get):
        self.assertEqual(self.post(project_id='1', gitlab_url='http://169.254.169.254').status_code, 400)
        self.assertEqual(self.post(project_id='../../x', gitlab_url='https://gitlab.example').status_code, 400)
        get.assert_not_called()

    @mock.patch('providers.views.requests.get')
    def test_server_replies_are_not_echoed_and_redirects_not_followed(self, get):
        get.return_value = _reply(500, 'SECRET internal page')
        response = self.post(project_id='7', gitlab_url='https://gitlab.example')
        self.assertNotIn('SECRET', response.content.decode())
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)

    @mock.patch('providers.views.requests.post')
    @mock.patch('providers.views.requests.get')
    def test_another_organisations_project_and_secret_stay_hidden(self, get, post):
        get.return_value = _reply(200, {'id': 123, 'name': 'x'})
        response = self.post(project_id='123', gitlab_url='https://attacker.example')
        self.assertEqual(response.status_code, 409)
        body = response.content.decode()
        self.assertNotIn('theirs', body)
        for call in post.call_args_list:  # nothing sent anywhere with their secret
            self.assertNotIn('OTHER-ORG-SECRET', str(call))
        self.binding.refresh_from_db()
        self.assertFalse(self.binding.webhook_configured)

    def test_integration_base_url_refuses_metadata(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/providers/integrations/', {
            'name': 'x', 'provider_type': 'gitlab', 'base_url': 'http://169.254.169.254/latest',
            'access_token': 't'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('base_url', response.json())

    def test_connection_test_refuses_metadata(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/providers/integrations/test/', {
            'provider_type': 'gitlab', 'base_url': 'http://metadata.google.internal', 'access_token': 't'},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('metadata', response.json()['message'])

    def test_observability_host_refuses_metadata(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post('/api/integrations/observability/', {
            'provider': 'elasticsearch', 'host': '169.254.169.254:9200', 'capabilities': ['logs']},
            format='json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('host', response.json())


class SenderRedirectTest(TestCase):
    def test_slack_and_teams_do_not_follow_redirects(self):
        from notifications.senders import slack, teams
        channel = mock.Mock()
        channel.get_webhook_url.return_value = 'https://hooks.example.com/x'
        payload = {'title': 't', 'summary': 's', 'severity': 'CRITICAL', 'issues': []}
        for sender in (slack, teams):
            with self.subTest(sender.__name__), \
                    mock.patch.object(sender, 'validate_public_url'), \
                    mock.patch.object(sender.requests, 'post', return_value=mock.Mock(status_code=200, text='ok')) as post:
                sender.send(channel, payload)
                self.assertIs(post.call_args.kwargs['allow_redirects'], False)
