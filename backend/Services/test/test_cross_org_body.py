"""A service can only be created in, or moved to, a project the caller may
change: never another organisation's (the project id comes in the body)."""
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Projects.models import Project
from Services.models import CustomService, Service
from Users.models import User


class ServiceProjectInBodyTest(APITestCase):
    def setUp(self):
        mine = Organisations.objects.create(name='Mine')
        self.victim = Project.objects.create(name='victim', organisation=Organisations.objects.create(name='Victim'))
        self.own = Project.objects.create(name='own', organisation=mine)
        self.client.force_authenticate(User.objects.create_user(
            username='a', email='a@mine.test', password='x', organisation=mine, role='admin', is_active=True))

    def test_create_in_another_organisations_project_is_refused(self):
        for url in ('/api/services/all/', '/api/services/custom/'):
            r = self.client.post(url, {'category': 'custom', 'name': 'planted', 'project': self.victim.id}, format='json')
            self.assertEqual(r.status_code, 400, (url, r.status_code, getattr(r, 'data', None)))
        self.assertFalse(Service.objects.filter(project=self.victim).exists())

    def test_create_in_own_project_works(self):
        r = self.client.post('/api/services/all/', {'category': 'custom', 'name': 'ok', 'project': self.own.id}, format='json')
        self.assertEqual(r.status_code, 201, getattr(r, 'data', None))

    def test_moving_a_service_to_another_organisation_is_refused(self):
        service = CustomService.objects.create(project=self.own, name='mine', category='custom')
        r = self.client.patch(f'/api/services/custom/{service.id}/', {'project': self.victim.id}, format='json')
        self.assertEqual(r.status_code, 400)
        service.refresh_from_db()
        self.assertEqual(service.project_id, self.own.id)
