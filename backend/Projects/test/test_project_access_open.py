"""``manage.py project_access_open``: the Community way back to open projects."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from Organisations.models import Organisations, Team
from Projects.models import Project, ProjectTeamAccess


class ProjectAccessOpenTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='Acme')
        self.team = Team.objects.create(organisation=self.org, name='T')
        self.a = Project.objects.create(name='a', organisation=self.org, access_mode='restricted')
        self.b = Project.objects.create(name='b', organisation=self.org, access_mode='restricted')
        ProjectTeamAccess.objects.create(project=self.a, team=self.team, role='viewer')

    def test_one_project(self):
        call_command('project_access_open', '--project', str(self.a.pk), stdout=StringIO())
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((self.a.access_mode, self.b.access_mode), ('organisation', 'restricted'))
        self.assertFalse(ProjectTeamAccess.objects.filter(project=self.a).exists())

    def test_whole_organisation(self):
        call_command('project_access_open', '--organisation', str(self.org.pk), '--all', stdout=StringIO())
        self.assertFalse(Project.objects.filter(access_mode='restricted').exists())

    def test_needs_a_target(self):
        with self.assertRaises(CommandError):
            call_command('project_access_open', stdout=StringIO())
