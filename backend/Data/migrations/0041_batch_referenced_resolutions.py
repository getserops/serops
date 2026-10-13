# Tracks which resolved Issue rows were injected into the AI prompt
# as Recent Resolutions Context for each batch. Surfaced on the issue
# detail UI so users can see *which* past resolutions informed the
# current analysis.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0040_issue_reasoning_confidence'),
    ]

    operations = [
        migrations.AddField(
            model_name='aianalyzedbatch',
            name='referenced_resolution_ids',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text='IDs of resolved issues that fed the AI prompt as context.',
            ),
        ),
    ]
