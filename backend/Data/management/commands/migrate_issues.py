from django.core.management.base import BaseCommand
from Data.models import AIAnalyzedBatch, Issue
import json
import ast
from django.utils import timezone

class Command(BaseCommand):
    help = 'Migrates issues from JSON analysis_text to the normalized Issue model'

    def handle(self, *args, **options):
        self.stdout.write("Starting issue migration...")
        
        batches = AIAnalyzedBatch.objects.exclude(analysis_text__isnull=True).exclude(analysis_text='')
        total_batches = batches.count()
        processed = 0
        issues_created = 0
        
        for batch in batches:
            try:
                # Parse analysis text
                analysis_text = batch.analysis_text
                if isinstance(analysis_text, str):
                    try:
                        analysis = json.loads(analysis_text)
                    except json.JSONDecodeError:
                        try:
                            analysis = ast.literal_eval(analysis_text)
                        except (ValueError, SyntaxError):
                            self.stderr.write(f"Failed to parse analysis for batch {batch.batch_id}")
                            continue
                else:
                    analysis = analysis_text
                
                if not isinstance(analysis, dict):
                    continue

                correlated_issues = analysis.get('correlated_issues', [])
                if not correlated_issues:
                    continue
                
                # Check duplication (naive check: delete and recreate for idempotency)
                Issue.objects.filter(batch=batch).delete()
                
                batch_issues = []
                for issue_data in correlated_issues:
                    if not isinstance(issue_data, dict):
                        continue
                        
                    severity = issue_data.get('severity', 'UNKNOWN').upper()
                    if severity not in dict(Issue.SEVERITY_CHOICES):
                        # Map unknown severities if possible or default to UNKNOWN
                        severity = 'UNKNOWN'
                    
                    batch_issues.append(Issue(
                        batch=batch,
                        severity=severity,
                        description=issue_data.get('description', 'No description'),
                        recommendation=issue_data.get('recommended_action', ''),
                        root_cause=issue_data.get('root_cause', '')
                    ))
                
                if batch_issues:
                    Issue.objects.bulk_create(batch_issues)
                    issues_created += len(batch_issues)
                
                processed += 1
                if processed % 10 == 0:
                    self.stdout.write(f"Processed {processed}/{total_batches} batches...")
                    
            except Exception as e:
                self.stderr.write(f"Error processing batch {batch.batch_id}: {str(e)}")
        
        self.stdout.write(self.style.SUCCESS(f"Migration completed. Processed {processed} batches, created {issues_created} issues."))
