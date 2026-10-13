"""
Management command to fix environment field for existing batches.

Usage:
    # Preview what would be changed (dry run)
    python manage.py fix_batch_environments --dry-run
    
    # Actually fix the batches
    python manage.py fix_batch_environments
    
    # Fix only for a specific project
    python manage.py fix_batch_environments --project demo
"""

from django.core.management.base import BaseCommand
from Data.models import AIAnalyzedBatch
from Projects.models import Project, ProjectEnvironment
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix environment field for existing batches based on log data or project settings'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without actually updating the database',
        )
        parser.add_argument(
            '--project',
            type=str,
            help='Only fix batches for a specific project name',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        project_filter = options.get('project')
        
        self.stdout.write(f"{'DRY RUN - ' if dry_run else ''}Fixing batch environments...")
        
        # Get batches to process
        batches = AIAnalyzedBatch.objects.all()
        
        if project_filter:
            batches = batches.filter(project__name__iexact=project_filter)
            self.stdout.write(f"Filtering to project: {project_filter}")
        
        # Build environment detection mapping
        known_envs = {
            'development': 'development', 'dev': 'development',
            'staging': 'staging', 'stage': 'staging', 'preprod': 'staging',
            'production': 'production', 'prod': 'production',
        }
        
        # Add custom environments from all projects
        for project in Project.objects.all():
            project_envs = ProjectEnvironment.objects.filter(
                project=project, is_active=True
            ).values_list('name', flat=True)
            for env_name in project_envs:
                known_envs[env_name.lower()] = env_name.lower()
        
        self.stdout.write(f"Known environments: {set(known_envs.values())}")
        
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for batch in batches:
            try:
                detected_env = self.detect_environment(batch, known_envs)
                current_env = batch.environment or 'production'
                
                if detected_env and detected_env != current_env:
                    self.stdout.write(
                        f"  {batch.batch_id}: {current_env} → {detected_env}"
                    )
                    
                    if not dry_run:
                        batch.environment = detected_env
                        batch.save(update_fields=['environment'])
                    
                    updated_count += 1
                else:
                    skipped_count += 1
                    
            except Exception as e:
                self.stderr.write(f"  Error processing {batch.batch_id}: {e}")
                error_count += 1
        
        self.stdout.write(self.style.SUCCESS(
            f"\n{'Would update' if dry_run else 'Updated'}: {updated_count} batches"
        ))
        self.stdout.write(f"Skipped (already correct): {skipped_count}")
        if error_count:
            self.stdout.write(self.style.ERROR(f"Errors: {error_count}"))
    
    def detect_environment(self, batch, known_envs):
        """Detect environment from batch log data."""
        logs = batch.data.get('logs', [])
        
        # Check first 10 logs for environment field
        for log in logs[:10]:
            source = log.get('_source', log)  # Handle both formats
            
            env_label = (
                source.get('environment') or 
                source.get('env') or 
                source.get('kubernetes', {}).get('labels', {}).get('environment')
            )
            
            if env_label:
                env_lower = env_label.lower()
                if env_lower in known_envs:
                    return known_envs[env_lower]
        
        # If project has only one active environment, use that
        if batch.project:
            active_envs = ProjectEnvironment.objects.filter(
                project=batch.project, is_active=True
            )
            if active_envs.count() == 1:
                return active_envs.first().name
        
        return None  # Couldn't detect, keep current
