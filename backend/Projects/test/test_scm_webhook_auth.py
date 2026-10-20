"""
The SCM webhook receiver authenticates every caller (2026-10-20 review).

Before: a binding created without a webhook_secret accepted any payload,
so anyone who guessed the sequential binding id could inject code-change
data into a victim's project. Now every binding gets a secret on
creation, and the receiver fails closed if one is somehow missing.
"""
import hashlib
import hmac
import json

from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from Projects.models import Project, ProjectService, SCMBinding
from providers.models import ProviderIntegration


class SCMWebhookAuthTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Hook Org')
        project = Project.objects.create(name='hook', organisation=self.org)
        self.service = ProjectService.objects.create(project=project, name='svc')
        self.integration = ProviderIntegration.objects.create(
            organisation=self.org, name='gh', provider_type='github')
        self.client = APIClient()

    def binding(self):
        return SCMBinding.objects.create(
            project_service=self.service, integration=self.integration,
            repository_id='r1', repository_name='r1')

    def test_binding_gets_a_secret_on_creation(self):
        self.assertTrue(self.binding().webhook_secret)

    def test_no_signature_is_rejected(self):
        b = self.binding()
        r = self.client.post(f'/api/webhooks/scm/{b.id}/', {'ref': 'refs/heads/main'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_wrong_signature_is_rejected(self):
        b = self.binding()
        r = self.client.post(f'/api/webhooks/scm/{b.id}/', {'ref': 'x'}, format='json',
                             HTTP_X_GITLAB_TOKEN='not-the-secret')
        self.assertEqual(r.status_code, 403)

    def test_empty_secret_fails_closed(self):
        b = self.binding()
        # Force the legacy state the fix guards against.
        SCMBinding.objects.filter(pk=b.pk).update(webhook_secret='')
        b.refresh_from_db()
        self.assertEqual(b.webhook_secret, '')
        r = self.client.post(f'/api/webhooks/scm/{b.id}/', {'ref': 'x'}, format='json',
                             HTTP_X_GITLAB_TOKEN='')
        self.assertEqual(r.status_code, 403)

    def test_correct_gitlab_token_is_accepted(self):
        b = self.binding()
        r = self.client.post(f'/api/webhooks/scm/{b.id}/', {'ref': 'refs/heads/main', 'commits': []},
                             format='json', HTTP_X_GITLAB_TOKEN=b.webhook_secret,
                             HTTP_X_GITLAB_EVENT='Push Hook')
        self.assertNotIn(r.status_code, (401, 403))

    def test_correct_github_hmac_is_accepted(self):
        b = self.binding()
        body = json.dumps({'ref': 'refs/heads/main', 'commits': []}).encode()
        sig = 'sha256=' + hmac.new(b.webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        r = self.client.post(f'/api/webhooks/scm/{b.id}/', data=body, content_type='application/json',
                             HTTP_X_HUB_SIGNATURE_256=sig, HTTP_X_GITHUB_EVENT='push')
        self.assertNotIn(r.status_code, (401, 403))


class LegacyProjectTokenNotLeakedTest(TestCase):
    """GET /api/providers/ must never return the stored GitLab token,
    not even its ciphertext (2026-10-20 review)."""

    def test_token_absent_from_list(self):
        from Users.models import User
        from providers.models import GitlabProject
        org = Organisations.objects.create(name='TokLeak Org')
        GitlabProject.objects.create(gitlab_url='u', username='u', name='n',
                                     project_id='88', access_token='glpat-SECRET', organisation=org)
        user = User.objects.create_user(username='t', email='t@tokleak.x', password='x',
                                        organisation=org, role='viewer', is_active=True)
        client = APIClient(); client.force_authenticate(user=user)
        r = client.get('/api/providers/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('glpat-SECRET', body)
        self.assertNotIn('access_token', body)
