"""
Add partial unique constraint on Issue fingerprint to prevent duplicate issues.

Fixes TOCTOU race condition where two concurrent threads can both find no existing
issue and both create new issues with the same fingerprint.

Uses a partial unique index: (fingerprint, project) WHERE status IN ('OPEN', 'MUTED')
so resolved issues don't block new issues with the same fingerprint after the dedup
window expires.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0026_add_performance_indexes'),
    ]

    operations = [
        # Add partial unique constraint: only one OPEN/MUTED issue per fingerprint+project
        migrations.AddConstraint(
            model_name='issue',
            constraint=models.UniqueConstraint(
                fields=['fingerprint', 'project'],
                condition=models.Q(status__in=['OPEN', 'MUTED']),
                name='unique_open_issue_per_fingerprint_project',
            ),
        ),
        # Remove the now-redundant regular index on (project, fingerprint)
        # since the unique constraint creates its own index
        migrations.RemoveIndex(
            model_name='issue',
            name='Data_issue_project_c6d827_idx',
        ),
    ]
