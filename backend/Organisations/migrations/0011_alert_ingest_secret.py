"""Q5-5 (2026-09-21): per-org alert-ingest secret (hash + prefix only)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Organisations', '0010_onboarding_rework'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisations',
            name='alert_ingest_secret_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='organisations',
            name='alert_ingest_secret_prefix',
            field=models.CharField(blank=True, default='', max_length=12),
        ),
        migrations.AddField(
            model_name='organisations',
            name='alert_ingest_secret_rotated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
