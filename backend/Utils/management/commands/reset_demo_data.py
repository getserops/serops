"""
Reset Demo Data Management Command

Cleans up all demo data for a fresh start.

Usage:
    python manage.py reset_demo_data --confirm
    python manage.py reset_demo_data --org-id=1 --confirm
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Remove all demo data from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            required=True,
            help='Confirm deletion (required)'
        )
        parser.add_argument(
            '--org-id',
            type=int,
            help='Specific organisation ID to delete (optional)'
        )
        parser.add_argument(
            '--keep-users',
            action='store_true',
            help='Keep user accounts'
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            raise CommandError('Use --confirm to proceed with deletion')

        org_id = options.get('org_id')
        keep_users = options['keep_users']

        self.stdout.write(self.style.WARNING('⚠️  Resetting demo data...'))

        try:
            with transaction.atomic():
                counts = self._delete_data(org_id, keep_users)
            
            self.stdout.write(self.style.SUCCESS('\n✅ Demo data reset complete!'))
            self.stdout.write('\n📊 Deleted:')
            for model, count in counts.items():
                self.stdout.write(f'   {model}: {count}')

        except Exception as e:
            raise CommandError(f'Failed to reset data: {e}')

    def _delete_data(self, org_id, keep_users):
        """Delete demo data and return counts."""
        from Data.models import AIAnalyzedBatch, Issue
        from Projects.models import Project, ProjectEnvironment, ProjectService
        from providers.models import Pipeline, Job, CodeChange, Deployment, ProviderIntegration
        from Organisations.models import Organisations
        from Users.models import User
        
        counts = {}
        
        # Build base queryset
        if org_id:
            orgs = Organisations.objects.filter(id=org_id)
        else:
            orgs = Organisations.objects.filter(name__icontains='Demo')
        
        org_ids = list(orgs.values_list('id', flat=True))
        
        if not org_ids:
            self.stdout.write('   No demo organisations found')
            return counts
        
        # Delete in dependency order
        
        # 1. Issues
        issues = Issue.objects.filter(project__organisation_id__in=org_ids)
        counts['Issues'] = issues.count()
        issues.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Issues"]} issues')
        
        # 2. Batches
        batches = AIAnalyzedBatch.objects.filter(project__organisation_id__in=org_ids)
        counts['Batches'] = batches.count()
        batches.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Batches"]} batches')
        
        # 3. Code Changes
        projects = Project.objects.filter(organisation_id__in=org_ids)
        project_ids = list(projects.values_list('id', flat=True))
        code_changes = CodeChange.objects.filter(project_id__in=[str(p) for p in project_ids])
        counts['CodeChanges'] = code_changes.count()
        code_changes.delete()
        self.stdout.write(f'   ✓ Deleted {counts["CodeChanges"]} code changes')
        
        # 4. Jobs and Pipelines
        jobs = Job.objects.filter(pipeline__environment__in=['production', 'staging', 'development'])
        counts['Jobs'] = jobs.count()
        jobs.delete()
        
        pipelines = Pipeline.objects.filter(environment__in=['production', 'staging', 'development'])
        counts['Pipelines'] = pipelines.count()
        pipelines.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Pipelines"]} pipelines, {counts["Jobs"]} jobs')
        
        # 5. Project Environments
        envs = ProjectEnvironment.objects.filter(project__organisation_id__in=org_ids)
        counts['Environments'] = envs.count()
        envs.delete()
        
        # 6. Project Services
        services = ProjectService.objects.filter(project__organisation_id__in=org_ids)
        counts['Services'] = services.count()
        services.delete()
        
        # 7. Projects
        counts['Projects'] = projects.count()
        projects.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Projects"]} projects')
        
        # 8. Integrations
        integrations = ProviderIntegration.objects.filter(organisation_id__in=org_ids)
        counts['Integrations'] = integrations.count()
        integrations.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Integrations"]} integrations')
        
        # 9. Users (optional)
        if not keep_users:
            users = User.objects.filter(organisation_id__in=org_ids)
            counts['Users'] = users.count()
            users.delete()
            self.stdout.write(f'   ✓ Deleted {counts["Users"]} users')
        
        # 10. Organisations
        counts['Organisations'] = orgs.count()
        orgs.delete()
        self.stdout.write(f'   ✓ Deleted {counts["Organisations"]} organisations')
        
        return counts
