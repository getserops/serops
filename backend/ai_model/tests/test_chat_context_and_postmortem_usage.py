"""
Chat and post-mortems see what the analysis saw (phase 3 Track 4, 2026-11-16).

1. The chat context named the service of a stored log from ``service_name``
   only; batches store it as ``_source['service']``, so most logs showed as
   ``[unknown]``.
2. The chat's code changes came only from legacy GitLab-linked rows: never
   the batch's own commits, never a GitHub (or other SCM-bound) repository.
3. Post-mortem drafts dropped their token counts, so their spend never
   reached AI Usage or the monthly budget.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project, ProjectService, SCMBinding
from Users.models import User


class _ChatBase(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Chat Org')
        self.user = User.objects.create_user(
            username='chatter', email='chatter@test.com', password='Pass1234!',
            organisation=self.org, role='admin', is_active=True,
        )
        self.project = Project.objects.create(name='wallet', organisation=self.org)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _batch(self, data, when=None):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'b-{AIAnalyzedBatch.objects.count() + 1}', project=self.project,
            organisation=self.org, timestamp=when or timezone.now(), data=data,
        )

    def _ask(self, batch, message):
        with patch('ai_model.views.process_ai_request', return_value=('ok', None)) as ai:
            r = self.client.post('/api/chat/generate-text/', {
                'type': 'chat', 'ai_model': 'claude',
                'prompt': {'message': message}, 'batch_id': batch.batch_id,
            }, format='json')
        self.assertIn(r.status_code, (200, 201), r.content)
        return ai.call_args_list[-1][0][0]


class ChatLogServiceTest(_ChatBase):
    def test_log_service_comes_from_the_stored_service_field(self):
        batch = self._batch({'logs': [{'_source': {
            'message': 'deadlock detected (POST /transfers)', '@timestamp': '2026-10-18T14:20:00Z',
            'service': 'wallet-api', 'level': 'ERROR'}}]})
        prompt = self._ask(batch, 'Show me the error logs')
        self.assertIn('[wallet-api]', prompt)
        self.assertNotIn('[unknown]', prompt)


class ChatCodeChangesTest(_ChatBase):
    def test_chat_sees_the_batchs_own_commits(self):
        batch = self._batch({
            'logs': [{'_source': {'message': 'deadlock detected', 'service': 'wallet-api'}}],
            'code_changes': [{
                'sha': 'a17c3e90', 'short_sha': 'a17c3e90', 'message': 'fix(wallet): fresher balance check on transfers',
                'author': 'sami', 'timestamp': '2026-10-18T14:15:00Z',
                'files': [{'path': 'wallet/transfers.py', 'diff': '-first, second = sorted([src_id, dst_id])'}],
            }],
        })
        prompt = self._ask(batch, 'Which commit changed this?')
        self.assertIn('a17c3e9', prompt)
        self.assertNotIn('No recent code changes found', prompt)

    def test_without_batch_commits_the_projects_github_repository_is_read(self):
        from providers.models import CodeChange, ProviderIntegration
        integ = ProviderIntegration.objects.create(name='GH', provider_type='github', category='devops',
                                                   organisation=self.org)
        svc = ProjectService.objects.create(project=self.project, name='wallet-api')
        SCMBinding.objects.create(project_service=svc, integration=integ, repository_id='4242',
                                  repository_name='acme/wallet', repository_url='https://github.com/acme/wallet',
                                  default_branch='main')
        now = timezone.now()
        CodeChange.objects.create(organisation=self.org, provider='github', project_id='4242',
                                  commit_sha='b2e4f6011122', commit_message='lock the source wallet first',
                                  author_name='sami', timestamp=now - timedelta(hours=1), branch='main')
        CodeChange.objects.create(organisation=self.org, provider='github', project_id='9999',
                                  commit_sha='c0ffee000000', commit_message='another repository',
                                  author_name='lea', timestamp=now - timedelta(hours=1), branch='main')
        batch = self._batch({'logs': [{'_source': {'message': 'deadlock detected', 'service': 'wallet-api'}}]},
                            when=now)
        prompt = self._ask(batch, 'Did a commit cause this?')
        self.assertIn('b2e4f60', prompt)
        self.assertNotIn('c0ffee0', prompt)


class PostmortemUsageTest(TestCase):
    def test_draft_tokens_reach_ai_usage(self):
        from ai_model.models import AITokenUsage
        from ai_model.postmortem import _ai_generate
        org = Organisations.objects.create(name='PM Org')
        project = Project.objects.create(name='pm', organisation=org)
        batch = AIAnalyzedBatch.objects.create(batch_id='pm-1', project=project, organisation=org,
                                               timestamp=timezone.now(), data={})
        with patch('ai_model.ai_service.generate_for_organisation',
                   return_value=('# Post-mortem\n...', 'claude', None, 1200, 800)):
            text = _ai_generate('prompt', batch)
        self.assertTrue(text.startswith('# Post-mortem'))
        usage = AITokenUsage.objects.get(organisation=org)
        self.assertEqual((usage.usage_type, usage.tokens_input, usage.tokens_output, usage.batch_id),
                         ('postmortem', 1200, 800, batch.pk))
