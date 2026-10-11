"""Add preprocessing-stat fields to AIAnalyzedBatch.

Instrumentation for the AI-cost visibility work (2026-08-31). Every
batch now records four counters populated by analyze_batch:

  logs_raw_count              — what came in
  logs_after_severity_filter  — what survived the INFO/DEBUG cull
  logs_unique_patterns        — what Smart Aggregation grouped down to
  logs_sent_to_ai             — what the AI actually saw

Legacy rows default to 0 (safe — the dashboard cards that consume
these will skip zero-value batches). No data migration needed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0041_batch_referenced_resolutions'),
    ]

    operations = [
        migrations.AddField(
            model_name='aianalyzedbatch',
            name='logs_raw_count',
            field=models.IntegerField(
                default=0,
                help_text='Log-event count in batch.data before any prompt-side filtering.',
            ),
        ),
        migrations.AddField(
            model_name='aianalyzedbatch',
            name='logs_after_severity_filter',
            field=models.IntegerField(
                default=0,
                help_text='Log count after dropping INFO/DEBUG for the AI prompt.',
            ),
        ),
        migrations.AddField(
            model_name='aianalyzedbatch',
            name='logs_unique_patterns',
            field=models.IntegerField(
                default=0,
                help_text='Unique signature count after Smart Aggregation (grouping identical errors).',
            ),
        ),
        migrations.AddField(
            model_name='aianalyzedbatch',
            name='logs_sent_to_ai',
            field=models.IntegerField(
                default=0,
                help_text='Actual log-line count sent to the AI (capped by aggregation slots).',
            ),
        ),
    ]
