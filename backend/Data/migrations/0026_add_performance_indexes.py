# Generated manually for Phase 2 performance optimization
# Adds composite indexes for frequently queried columns

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0025_cicd_architecture_phase1'),
    ]

    operations = [
        # Composite index for Issues filtered by project + time + status
        # Optimizes dashboard queries showing recent open/resolved issues
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(
                fields=['project', 'created_at', 'status'],
                name='data_issue_proj_time_status_idx'
            ),
        ),

        # Composite index for Issues filtered by project + time + severity
        # Optimizes queries grouping issues by severity over time
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(
                fields=['project', 'created_at', 'severity'],
                name='data_issue_proj_time_sev_idx'
            ),
        ),

        # Composite index for Issues filtered by project + environment + status
        # Optimizes multi-environment queries (dev/staging/prod filtering)
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(
                fields=['project', 'environment', 'status'],
                name='data_issue_proj_env_status_idx'
            ),
        ),

        # Composite index for Issues filtered by batch + created_at
        # Optimizes batch detail queries showing issues chronologically
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(
                fields=['batch', 'created_at'],
                name='data_issue_batch_time_idx'
            ),
        ),
    ]
