"""
Management command to backfill correlation fields for existing issues.
Run this after adding the correlation fields migration.

Usage: python manage.py backfill_correlations
"""

from django.core.management.base import BaseCommand
from Data.models import Issue
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill correlation fields (has_commit_correlation, has_metric_correlation, etc.) for existing issues'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=500,
            help='Number of issues to process per batch (default: 500)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without actually saving'
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        dry_run = options['dry_run']
        
        total_issues = Issue.objects.count()
        self.stdout.write(f"Starting backfill for {total_issues} issues...")
        
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be saved"))
        
        updated_commit = 0
        updated_metric = 0
        processed = 0
        
        # Process in batches to avoid memory issues
        issues = Issue.objects.all().select_related('project').iterator(chunk_size=batch_size)
        
        for issue in issues:
            # Compute correlations
            issue._compute_correlations()
            
            if issue.has_commit_correlation:
                updated_commit += 1
            if issue.has_metric_correlation:
                updated_metric += 1
            
            if not dry_run:
                # Use update_fields to avoid triggering save() again
                Issue.objects.filter(pk=issue.pk).update(
                    has_commit_correlation=issue.has_commit_correlation,
                    has_metric_correlation=issue.has_metric_correlation,
                    linked_commits=issue.linked_commits,
                    metric_correlation_type=issue.metric_correlation_type
                )
            
            processed += 1
            
            if processed % 100 == 0:
                self.stdout.write(f"Processed {processed}/{total_issues} issues...")
        
        self.stdout.write(self.style.SUCCESS(
            f"Backfill complete: {processed} issues processed, "
            f"{updated_commit} with commit correlation, "
            f"{updated_metric} with metric correlation"
        ))
