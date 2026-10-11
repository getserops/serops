"""
Fix Orphaned Issues Management Command

Fixes issues that have batch.project set but issue.project is NULL.
This is a data migration to ensure proper org isolation.

Usage:
    python manage.py fix_orphan_issues --dry-run
    python manage.py fix_orphan_issues --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Fix issues with missing project FK (copy from batch.project)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be fixed without making changes'
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Actually apply the fixes'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of issues to fix at a time (default: 100)'
        )

    def handle(self, *args, **options):
        from Data.models import Issue
        
        dry_run = options['dry_run']
        apply = options['apply']
        batch_size = options['batch_size']

        if not dry_run and not apply:
            self.stdout.write(self.style.WARNING(
                'Use --dry-run to preview or --apply to fix'
            ))
            return

        # Find orphaned issues that can be fixed
        orphans = Issue.objects.filter(
            project__isnull=True,
            batch__project__isnull=False
        ).select_related('batch__project')
        
        total = orphans.count()
        self.stdout.write(f'Found {total} orphaned issues with fixable batch.project')

        if dry_run:
            # Show breakdown by project
            from collections import Counter
            project_counts = Counter()
            for issue in orphans[:500]:  # Sample
                project_counts[issue.batch.project.name] += 1
            
            self.stdout.write('\n📊 Would fix issues for these projects:')
            for project, count in project_counts.most_common():
                self.stdout.write(f'  {project}: {count}')
            
            self.stdout.write(self.style.NOTICE(
                f'\n💡 Run with --apply to fix {total} issues'
            ))
            return

        # Apply fixes in batches
        self.stdout.write(f'\n🔧 Fixing {total} orphaned issues...')
        
        fixed = 0
        while True:
            batch = list(orphans[:batch_size])
            if not batch:
                break
            
            with transaction.atomic():
                for issue in batch:
                    issue.project = issue.batch.project
                    issue.save(update_fields=['project'])
                    fixed += 1
            
            self.stdout.write(f'  Fixed {fixed}/{total}...')
            
            # Re-query after fixes
            orphans = Issue.objects.filter(
                project__isnull=True,
                batch__project__isnull=False
            ).select_related('batch__project')

        # Verify
        remaining = Issue.objects.filter(project__isnull=True).count()
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Fixed {fixed} issues'))
        self.stdout.write(f'Remaining orphans: {remaining}')
