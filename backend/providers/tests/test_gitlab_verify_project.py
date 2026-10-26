"""
POST /api/providers/verify-project/: the caller picks the GitLab server, so
the view must not become a way to read other URLs (cloud metadata, other
paths of an internal server) or to write another organisation's pipelines.
"""
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from providers.models import GitlabProject, Pipeline
from Users.models import User

URL = '/api/providers/verify-project/'


def _reply(status, body):
    r = mock.Mock(status_code=status, text=str(body))
    r.json.return_value = body
    return r


class VerifyGitLabProjectTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='Caller org')
        cls.other = Organisations.objects.create(name='Other org')
        cls.user = User.objects.create_user(username='dev', email='dev@a.example', password='x',
                                            organisation=cls.org, role='user', is_active=True)
        cls.theirs = GitlabProject.objects.create(
            gitlab_url='https://gitlab.other.example', username='o', name='theirs', project_id='123',
            access_token='t', organisation=cls.other)

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def post(self, **body):
        return self.client.post(URL, {'access_token': 'tok', **body}, format='json')

    @mock.patch('providers.views.requests.get')
    def test_cloud_metadata_is_refused(self, get):
        for url in ('http://169.254.169.254', 'http://metadata.google.internal'):
            response = self.post(project_id='1', gitlab_url=url)
            self.assertEqual(response.status_code, 400, url)
        get.assert_not_called()

    @mock.patch('providers.views.requests.get')
    def test_project_id_cannot_leave_the_projects_route(self, get):
        for bad in ('../../latest/meta-data', '1/../../x', '%2e%2e', '..', '', 'a//b'):
            response = self.post(project_id=bad, gitlab_url='https://gitlab.example')
            self.assertEqual(response.status_code, 400, bad)
        get.assert_not_called()

    @mock.patch('providers.views.requests.get')
    def test_query_and_fragment_stay_inside_the_id(self, get):
        get.return_value = _reply(404, {})
        self.post(project_id='1?x=#y', gitlab_url='https://gitlab.example')
        self.assertEqual(get.call_args.args[0], 'https://gitlab.example/api/v4/projects/1%3Fx%3D%23y')

    @mock.patch('providers.views.requests.get')
    def test_group_path_is_one_segment_and_redirects_are_not_followed(self, get):
        get.return_value = _reply(404, {})
        self.post(project_id='group/sub/app', gitlab_url='https://gitlab.example/some/page')
        self.assertEqual(get.call_args.args[0], 'https://gitlab.example/api/v4/projects/group%2Fsub%2Fapp')
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)
        self.assertTrue(get.call_args.kwargs['timeout'])

    @mock.patch('providers.views.requests.get')
    def test_private_self_hosted_gitlab_still_works(self, get):
        get.side_effect = [_reply(200, {'id': 7, 'name': 'app'}), _reply(200, [{'id': 1, 'status': 'success'}])]
        response = self.post(project_id='7', gitlab_url='http://10.0.0.5:8080')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get.call_args_list[0].args[0], 'http://10.0.0.5:8080/api/v4/projects/7')

    @mock.patch('providers.views.requests.get')
    def test_server_replies_are_not_echoed(self, get):
        get.return_value = _reply(500, 'SECRET internal page')
        response = self.post(project_id='7', gitlab_url='https://gitlab.example')
        self.assertNotIn('SECRET', response.content.decode())

    @mock.patch('providers.views.requests.get')
    def test_pipelines_keep_only_known_fields(self, get):
        get.side_effect = [_reply(200, {'id': 7}),
                           _reply(200, [{'id': 1, 'status': 'failed', 'AccessKeyId': 'AKIA'}])]
        response = self.post(project_id='7', gitlab_url='https://gitlab.example')
        self.assertNotIn('AKIA', response.content.decode())
        self.assertEqual(response.json()['pipelines'][0]['status'], 'failed')

    @mock.patch('providers.views.requests.get')
    def test_another_organisations_project_is_neither_used_nor_written(self, get):
        get.side_effect = [_reply(200, {'id': 123}), _reply(200, [{'id': 99, 'status': 'success', 'ref': 'x'}])]
        response = self.post(project_id='123')
        self.assertEqual(response.status_code, 200)
        # Their self-hosted URL isn't used for a caller of another organisation.
        self.assertEqual(get.call_args_list[0].args[0], 'https://gitlab.com/api/v4/projects/123')
        self.assertFalse(Pipeline.objects.filter(project=self.theirs).exists())
