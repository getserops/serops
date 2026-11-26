"""Overview part A (1.5.6): the service-health endpoint returns every service
(it used to cut the list to 12 while the page said "19 services monitored"),
and each service says which open issues name it as affected."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project, ProjectService
from Services.models import Service

URL = '/api/data/analytics/service-health/'


class ServiceHealthAllAndAffectedByTest(TestCase):

    def setUp(self):
        cache.clear()
        self.org = Organisations.objects.create(name='sh-org')
        self.user = get_user_model().objects.create_user(
            username='sh', email='sh@example.com', password='x-Long-pass-1',
            organisation=self.org, role='admin')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='sh-b', project=self.project, organisation=self.org,
            timestamp=timezone.now(), environment='prod')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.n = 0

    def _service(self, name):
        return Service.objects.create(name=name, project=self.project, category='web', status='active')

    def _issue(self, component, affected, severity='CRITICAL', status='OPEN', environment='prod',
               org=None, project='same', batch=None):
        self.n += 1
        return Issue.objects.create(
            batch=batch or self.batch, project=self.project if project == 'same' else project,
            organisation=org or self.org, severity=severity, status=status,
            environment=environment, component=component, affected_services=affected,
            fingerprint=f'sh-fp-{self.n}', description=f'issue {self.n}')

    def _get(self, query=''):
        cache.clear()
        r = self.client.get(URL + query)
        self.assertEqual(r.status_code, 200)
        return r.data, {s['name']: s for s in r.data['services']}

    def test_every_service_is_returned_worst_first(self):
        for i in range(19):
            self._service(f'svc-{i:02d}')
        self._issue('svc-07', [])
        data, by_name = self._get()
        self.assertEqual(data['total_services'], 19)
        self.assertEqual(len(data['services']), 19)
        self.assertEqual(data['services'][0]['name'], 'svc-07')

    def test_affected_by_lists_components_of_open_issues(self):
        for name in ('redis-cache', 'Checkout', 'web', 'orders', 'search'):
            self._service(name)
        # Case does not matter; the issue's own component and a name that
        # is not a monitored service are ignored.
        self._issue('redis-cache', ['checkout', 'WEB', 'redis-cache', 'not-a-service'])
        self._issue('search', ['web'], severity='WARNING')
        self._issue('search', ['Web'], severity='INFO')         # same component twice: listed once
        self._issue('orders', ['checkout'], status='RESOLVED')   # not open
        data, by_name = self._get()
        self.assertEqual(by_name['Checkout']['affected_by'], ['redis-cache'])
        self.assertEqual(by_name['web']['affected_by'], ['redis-cache', 'search'])
        self.assertEqual(by_name['redis-cache']['affected_by'], [])
        self.assertEqual(by_name['orders']['affected_by'], [])
        self.assertEqual(by_name['search']['affected_by'], [])
        self.assertNotIn('not-a-service', by_name)
        self.assertEqual(data['total_services'], 5)

    def test_affected_by_follows_the_environment_filter(self):
        self._service('web')
        self._issue('redis-cache', ['web'], environment='staging')
        _, by_name = self._get('?environment=prod')
        self.assertEqual(by_name['web']['affected_by'], [])
        _, by_name = self._get('?environment=staging')
        self.assertEqual(by_name['web']['affected_by'], ['redis-cache'])
        _, by_name = self._get()
        self.assertEqual(by_name['web']['affected_by'], ['redis-cache'])

    def test_affected_by_stays_in_the_service_project(self):
        # Two projects each have a "web"; an issue names "web" in one of them.
        # A service's own issues are matched by project and name, and so is
        # affected_by (the issue's project, else its batch's).
        self._service('web')
        other = Project.objects.create(name='admin', organisation=self.org)
        Service.objects.create(name='web', project=other, category='web', status='active')
        ob = AIAnalyzedBatch.objects.create(batch_id='sh-b2', project=other, organisation=self.org,
                                            timestamp=timezone.now(), environment='prod')
        self._issue('redis-cache', ['web'])
        self._issue('auth', ['web'], project=None, batch=ob)   # project from the batch
        data, _ = self._get()
        by_project = {s['name'] + '@' + str(i): s for i, s in enumerate(data['services'])}
        got = sorted(tuple(s['affected_by']) for s in by_project.values())
        self.assertEqual(got, [('auth',), ('redis-cache',)])

    def test_each_service_names_its_project(self):
        # Two projects each have a "notifier"; the Overview tells them apart
        # by project_name. A legacy ProjectService carries its project too.
        self._service('notifier')
        fleet = Project.objects.create(name='Fleet', organisation=self.org)
        Service.objects.create(name='notifier', project=fleet, category='web', status='active')
        legacy = Project.objects.create(name='Legacy', organisation=self.org)
        ProjectService.objects.create(name='billing', project=legacy)
        data, _ = self._get()
        got = sorted((s['name'], s['project_name']) for s in data['services'])
        self.assertEqual(got, [('billing', 'Legacy'), ('notifier', 'Fleet'), ('notifier', 'shop')])

    def test_other_organisation_is_not_counted(self):
        self._service('web')
        other = Organisations.objects.create(name='sh-other')
        op = Project.objects.create(name='o', organisation=other)
        ob = AIAnalyzedBatch.objects.create(batch_id='sh-ob', project=op, organisation=other,
                                            timestamp=timezone.now(), environment='prod')
        self._issue('redis-cache', ['web'], org=other, project=op, batch=ob)
        _, by_name = self._get()
        self.assertEqual(by_name['web']['affected_by'], [])

    def test_query_count_does_not_grow_with_services(self):
        for i in range(3):
            self._service(f'a-{i}')
        self._issue('a-0', ['a-1'])
        cache.clear()
        with CaptureQueriesContext(connection) as few:
            self.client.get(URL)
        for i in range(30):
            self._service(f'b-{i}')
            self._issue(f'b-{i}', ['a-1'])
        cache.clear()
        with CaptureQueriesContext(connection) as many:
            self.client.get(URL)
        self.assertEqual(len(few), len(many))
