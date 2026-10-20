"""
Ids in request bodies: a writable relation can only point at the
requester's own rows.

The route walkers send empty bodies, so they can't see this. Here every
serializer is built for a requester of one organisation and each writable
relation must have a limited queryset (or be listed in SHARED with why).
A new serializer with an open relation fails until it is limited, e.g. with
``Middlewares.project_access.limit_relations``.
"""
import importlib
import inspect

from django.test import TestCase
from rest_framework import serializers
from rest_framework.relations import ManyRelatedField, RelatedField
from rest_framework.test import APIClient

APPS = ['Data', 'Projects', 'Services', 'providers', 'notifications', 'integrations', 'org_settings', 'traces',
        'Organisations', 'Users', 'ai_model', 'Utils']

SHARED = {
    'org_settings.OrganisationAISettingsSerializer.default_provider': 'AI provider catalogue, shared by every organisation',
    'org_settings.OrganisationAISettingsSerializer.fallback_provider': 'AI provider catalogue, shared by every organisation',
    'org_settings.OrganisationAPIKeySerializer.provider': 'AI provider catalogue, shared by every organisation',
    'Projects.ProjectCreateSerializer.organisation': "the view sets it to the requester's organisation",
    'Projects.ProjectDeploymentSerializer.project': 'validate_project checks the organisation',
    'Projects.ProjectDeploymentSerializer.environment': "validate() checks it belongs to the project",
    'Projects.ProjectDeploymentSerializer.cluster': "validate() checks the requester's organisation",
    'integrations.ObservabilityIntegrationSerializer.cluster': "validate_cluster checks the requester's organisation",
}


def writable_relations(user):
    request = type('Request', (), {'user': user})()
    for app in APPS:
        try:
            module = importlib.import_module(f'{app}.serializers')
        except ModuleNotFoundError:
            continue
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if not issubclass(cls, serializers.Serializer) or cls.__module__ != module.__name__:
                continue
            for field_name, field in cls(context={'request': request}).fields.items():
                relation = field.child_relation if isinstance(field, ManyRelatedField) else field
                if isinstance(relation, RelatedField) and not field.read_only:
                    yield f'{app}.{name}.{field_name}', relation


class BodyRelationCoverageTest(TestCase):
    def test_every_writable_relation_is_limited(self):
        from Organisations.models import Organisations
        from Users.models import User
        org = Organisations.objects.create(name='Mine')
        user = User.objects.create_user(username='u', email='u@mine.test', password='x', organisation=org,
                                        role='admin', is_active=True)
        open_relations = []
        for key, relation in writable_relations(user):
            if key in SHARED:
                continue
            queryset = relation.queryset
            queryset = queryset.all() if queryset is not None else None
            if queryset is None or not queryset.query.where.children:
                open_relations.append(key)
        self.assertEqual(open_relations, [], '\nWritable relations open to any id:\n' + '\n'.join(open_relations))


class BodyRelationBehaviourTest(TestCase):
    def setUp(self):
        from Organisations.models import Organisations
        from Projects.models import Project, ProjectEnvironment
        from integrations.models import Cluster
        from Users.models import User
        mine = Organisations.objects.create(name='Mine')
        victim = Organisations.objects.create(name='Victim')
        self.own = Project.objects.create(name='own', organisation=mine)
        self.own_env = ProjectEnvironment.objects.create(project=self.own, name='production')
        self.victim_project = Project.objects.create(name='victim-secret-name', organisation=victim)
        self.victim_env = ProjectEnvironment.objects.create(project=self.victim_project, name='production')
        self.victim_cluster = Cluster.objects.create(organisation=victim, name='victim-cluster')
        self.client = APIClient()
        self.client.force_authenticate(User.objects.create_user(
            username='a', email='a@mine.test', password='x', organisation=mine, role='admin', is_active=True))

    def test_cannot_subscribe_to_another_organisations_project(self):
        r = self.client.post('/api/notification/subscriptions/', {'project': self.victim_project.id}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/notification/subscriptions/', {'project': self.own.id}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.client.put(f'/api/notification/subscriptions/{r.data.get("id") or 0}/',
                            {'project': self.victim_project.id}, format='json')
        self.assertIn(r.status_code, (400, 404))

    def test_escalation_rule_cannot_name_another_organisations_project(self):
        r = self.client.post('/api/notification/escalation-rules/', {
            'project': self.victim_project.id, 'severity': 'CRITICAL',
            'level_1_delay_minutes': 5, 'level_2_delay_minutes': 15}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('victim-secret-name', r.content.decode())

    def test_deployment_refuses_foreign_environment_and_cluster(self):
        r = self.client.post('/api/projects/deployments/', {
            'project': self.own.id, 'environment': self.victim_env.id, 'name': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/projects/deployments/', {
            'project': self.own.id, 'environment': self.own_env.id, 'cluster': self.victim_cluster.id,
            'namespace': 'ns', 'name': 'y'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('victim-cluster', r.content.decode())

    def test_project_service_cannot_move_to_another_organisation(self):
        from Projects.models import ProjectService
        service = ProjectService.objects.create(project=self.own, name='svc')
        # The edit form ignores ``project`` (moving needs its own endpoint).
        self.client.patch(f'/api/projects/services/{service.id}/', {'project': self.victim_project.id}, format='json')
        service.refresh_from_db()
        self.assertEqual(service.project_id, self.own.id)
