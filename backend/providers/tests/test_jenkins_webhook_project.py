"""
A Jenkins build reported through a CI/CD binding belongs to the binding's
project, and analyses on a store SerOps cannot write to (Loki, Splunk...)
still see it. Found by the local journey suite (launch plan 9.9): the
webhook stored the build with no organisation or project, and analyses only
read CI/CD events back from Elasticsearch.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from Data.tasks import _cicd_from_database
from Organisations.models import Organisations
from Projects.models import CICDBinding, Project, ProjectService
from providers.models import Pipeline, ProviderIntegration


class JenkinsBuildOwnershipTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.service = ProjectService.objects.create(project=self.project, name='payments')
        integration = ProviderIntegration.objects.create(
            organisation=self.org, name='Acme Jenkins', provider_type='jenkins', category='cicd')
        self.binding = CICDBinding.objects.create(
            project_service=self.service, integration=integration, binding_type='deploy',
            pipeline_id='payments-deploy', pipeline_name='payments deploy', webhook_secret='whsec')

    def post_build(self, number, status='FAILURE'):
        # The body of the Jenkinsfile example in docs/src/integrations/jenkins.md.
        return APIClient().post(f'/api/webhooks/jenkins/{self.binding.id}/', {
            'job_name': 'payments-deploy', 'build_number': str(number), 'status': status, 'branch': 'null',
        }, format='json', HTTP_X_JENKINS_TOKEN='whsec')

    def test_build_belongs_to_the_bindings_project(self):
        self.assertEqual(self.post_build(7).status_code, 200)
        p = Pipeline.objects.get()
        self.assertEqual(p.organisation, self.org)
        self.assertEqual(p.provider_metadata.get('serops_project_id'), self.project.id)
        self.assertEqual(p.provider_metadata.get('service_name'), 'payments')

    def test_analyses_see_the_build_without_elasticsearch(self):
        self.post_build(8)
        now = timezone.now()
        runs = _cicd_from_database(self.project, 'production', now - timedelta(minutes=15), now + timedelta(minutes=1))
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]['status'], 'failed')
        self.assertEqual(runs[0]['job_name'], 'payments-deploy')
        self.assertEqual(runs[0]['service_name'], 'payments')

    def test_same_job_and_build_in_two_organisations_are_two_builds(self):
        """Builds were unique on (provider, pipeline_id): another tenant's
        "payments-deploy" #7 overwrote this one and took over its organisation."""
        other_org = Organisations.objects.create(name='Other')
        other_project = Project.objects.create(name='shop', organisation=other_org)
        other_service = ProjectService.objects.create(project=other_project, name='payments')
        other_integration = ProviderIntegration.objects.create(
            organisation=other_org, name='Other Jenkins', provider_type='jenkins', category='cicd')
        other_binding = CICDBinding.objects.create(
            project_service=other_service, integration=other_integration, binding_type='deploy',
            pipeline_id='payments-deploy', webhook_secret='other-secret')
        self.assertEqual(self.post_build(7).status_code, 200)
        r = APIClient().post(f'/api/webhooks/jenkins/{other_binding.id}/', {
            'job_name': 'payments-deploy', 'build_number': '7', 'status': 'SUCCESS', 'branch': 'main',
        }, format='json', HTTP_X_JENKINS_TOKEN='other-secret')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Pipeline.objects.count(), 2)
        mine = Pipeline.objects.get(organisation=self.org)
        self.assertEqual(mine.status, 'failed')
        self.assertEqual(Pipeline.objects.get(organisation=other_org).status, 'success')

    def test_a_build_tagged_with_another_real_environment_is_left_out(self):
        self.post_build(9)
        p = Pipeline.objects.get()
        p.environment = 'staging'
        p.provider_metadata = {**p.provider_metadata, 'environment_source': 'explicit'}
        p.save()
        now = timezone.now()
        self.assertEqual(_cicd_from_database(self.project, 'production', now - timedelta(minutes=15), now), [])
