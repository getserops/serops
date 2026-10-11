from django.core.management.base import BaseCommand
from Data.models import AIAnalyzedBatch, Issue

class Command(BaseCommand):
    help = 'Fixes mismatches between batch.issue_count and actual number of issues'

    def handle(self, *args, **options):
        self.stdout.write("Checking for issue count mismatches...")
        
        batches = AIAnalyzedBatch.objects.all()
        updated_count = 0
        
        for batch in batches:
            actual_count = Issue.objects.filter(occurrences__batch=batch).distinct().count()
            
            if batch.issue_count != actual_count:
                self.stdout.write(
                    self.style.WARNING(
                        f"Mismatch for {batch.batch_id}: Stored={batch.issue_count}, Actual={actual_count}"
                    )
                )
                batch.issue_count = actual_count
                batch.save(update_fields=['issue_count'])
                updated_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Fixed {updated_count} batches."))
