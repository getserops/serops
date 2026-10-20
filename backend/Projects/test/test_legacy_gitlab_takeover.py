"""A CI/CD binding never takes over another organisation's legacy GitLab
project row (unique per GitLab project id across the install)."""
from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import GitlabProject, ProviderIntegration


class LegacyGitlabTakeoverTest(TestCase):
    def test_binding_with_another_organisations_project_id_leaves_it_alone(self):
        victim = Organisations.objects.create(name='Victim')
        attacker = Organisations.objects.create(name='Attacker')
        row = GitlabProject.objects.create(gitlab_url='https://gitlab.example', username='v', name='victim-repo',
                                           project_id='4242', access_token='victim-token', organisation=victim)
        integration = ProviderIntegration.objects.create(name='gl', provider_type='gitlab', organisation=attacker,
                                                         base_url='https://evil.example')
        service = ProjectService.objects.create(project=Project.objects.create(name='p', organisation=attacker), name='s')
        CICDBinding.objects.create(project_service=service, integration=integration, pipeline_id='4242')
        row.refresh_from_db()
        self.assertEqual(row.organisation, victim)
        self.assertEqual(row.gitlab_url, 'https://gitlab.example')
        self.assertEqual(row.get_access_token(), 'victim-token')

    def test_own_row_is_created_and_kept_fresh(self):
        org = Organisations.objects.create(name='Mine')
        integration = ProviderIntegration.objects.create(name='gl', provider_type='gitlab', organisation=org,
                                                         base_url='https://gitlab.example')
        service = ProjectService.objects.create(project=Project.objects.create(name='p', organisation=org), name='s')
        CICDBinding.objects.create(project_service=service, integration=integration, pipeline_id='77')
        self.assertEqual(GitlabProject.objects.get(project_id='77').organisation, org)
