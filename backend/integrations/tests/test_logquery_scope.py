"""Tests for LogQuery.scope_services_to_org — defence against a future
endpoint that accepts services from user input.

Today no endpoint sets LogQuery.services from user input; all callers
in Data/tasks.py populate it from server-controlled Project/Service
records. This helper exists so it's easy for a future endpoint to do
the right thing.
"""

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectService
from integrations.schemas import LogQuery


class TestScopeServicesToOrg(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org_a = Organisations.objects.create(
            name='Org A', website='https://a.example',
        )
        cls.org_b = Organisations.objects.create(
            name='Org B', website='https://b.example',
        )
        cls.proj_a = Project.objects.create(name='proj-a', organisation=cls.org_a)
        cls.proj_b = Project.objects.create(name='proj-b', organisation=cls.org_b)
        ProjectService.objects.create(
            project=cls.proj_a, name='api', service_type='application',
        )
        ProjectService.objects.create(
            project=cls.proj_a, name='worker', service_type='application',
        )
        ProjectService.objects.create(
            project=cls.proj_b, name='api',  # same name, different org!
            service_type='application',
        )

    def test_scope_keeps_only_names_owned_by_org(self):
        q = LogQuery(services=['api', 'worker'])
        q.scope_services_to_org(self.org_a)
        # Both belong to org A — both kept.
        self.assertEqual(sorted(q.services), ['api', 'worker'])

    def test_scope_drops_names_owned_by_another_org(self):
        # Note: 'stranger' doesn't exist anywhere; 'worker' exists only
        # in org A. Both must be dropped when scoped to org B.
        q = LogQuery(services=['api', 'worker', 'stranger'])
        q.scope_services_to_org(self.org_b)
        # 'api' also exists in org B → kept. 'worker' and 'stranger'
        # are not in org B → dropped.
        self.assertEqual(q.services, ['api'])

    def test_scope_returns_empty_for_none_org(self):
        q = LogQuery(services=['api'])
        q.scope_services_to_org(None)
        self.assertEqual(q.services, [])

    def test_scope_is_noop_for_empty_services(self):
        q = LogQuery(services=None)
        q.scope_services_to_org(self.org_a)
        self.assertIsNone(q.services)

        q = LogQuery(services=[])
        q.scope_services_to_org(self.org_a)
        self.assertEqual(q.services, [])

    def test_scope_chains_for_construction_fluency(self):
        # Chainable so a caller can do:
        #   LogQuery(services=user_input).scope_services_to_org(user.org)
        q = LogQuery(services=['api'])
        result = q.scope_services_to_org(self.org_a)
        self.assertIs(result, q)
