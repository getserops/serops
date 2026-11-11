"""
Open restricted projects to their whole organisation again.

Restricting projects to teams is managed in SerOps Enterprise. A Community
install that still has restricted projects (for example after removing the
``ee/`` directories) uses this command to undo it; built-in admins see every
project in the meantime.

    python manage.py project_access_open --project 12
    python manage.py project_access_open --organisation 3 --all
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Projects.models import Project, ProjectTeamAccess


class Command(BaseCommand):
    help = 'Open restricted projects to their whole organisation and remove their team grants.'

    def add_arguments(self, parser):
        parser.add_argument('--project', type=int, help='Project id')
        parser.add_argument('--organisation', type=int, help='Organisation id (with --all)')
        parser.add_argument('--all', action='store_true', help='Every restricted project of --organisation')

    def handle(self, *args, **opts):
        projects = Project.objects.filter(access_mode='restricted')
        if opts['project']:
            projects = projects.filter(pk=opts['project'])
        elif opts['organisation'] and opts['all']:
            projects = projects.filter(organisation_id=opts['organisation'])
        else:
            raise CommandError('Give --project ID, or --organisation ID --all.')
        opened = 0
        for project in projects:
            with transaction.atomic():
                ProjectTeamAccess.objects.filter(project=project).delete()
                project.access_mode = 'organisation'
                project.save(update_fields=['access_mode', 'updated_at'])
            opened += 1
            self.stdout.write(f'Opened "{project.name}" (id {project.pk}) to its organisation')
        if not opened:
            self.stdout.write('No restricted project matched.')
