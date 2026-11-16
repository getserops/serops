# Phase 3 review MT-2: spans carry their environment and project, so a batch
# reads only its own (plus unlabelled spans). Additive, reversible.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('traces', '0003_trace_org_scoped_identity'),
    ]

    operations = [
        migrations.AddField(
            model_name='span',
            name='environment',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='span',
            name='project_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddIndex(
            model_name='span',
            index=models.Index(fields=['service_name', 'environment', '-start_time'], name='span_svc_env_start_idx'),
        ),
    ]
