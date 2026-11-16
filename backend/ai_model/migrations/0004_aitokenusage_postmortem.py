from django.db import migrations, models


class Migration(migrations.Migration):
    """Post-mortem drafts are recorded in AI Usage (choices only, no schema change)."""

    dependencies = [
        ('ai_model', '0003_aitokenusage'),
    ]

    operations = [
        migrations.AlterField(
            model_name='aitokenusage',
            name='usage_type',
            field=models.CharField(choices=[('batch_analysis', 'Batch Analysis'), ('chat_message', 'Chat Message'), ('manual_analysis', 'Manual Analysis'), ('batch_reanalysis', 'Batch Re-analysis'), ('postmortem', 'Post-mortem Draft')], default='batch_analysis', max_length=20),
        ),
    ]
