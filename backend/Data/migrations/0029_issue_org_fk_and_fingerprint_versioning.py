"""
Schema migration for dedup hardening:
- Add organisation FK to Issue (C1 fix: null-project isolation)
- Replace old unique constraint with project__isnull=False condition
- Add new constraint for null-project issues (fingerprint+organisation)
- Widen fingerprint field to 70 chars (v4 prefix: 'v4:' + 32 hex = 35 chars)
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0028_remove_issue_data_issue_proj_time_status_idx_and_more'),
        ('Organisations', '0001_initial'),
    ]

    operations = [
        # 1. Add organisation FK (nullable for existing rows)
        migrations.AddField(
            model_name='issue',
            name='organisation',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='issues',
                to='Organisations.Organisations',
            ),
        ),
        # 2. Remove old constraint (no project__isnull condition)
        migrations.RemoveConstraint(
            model_name='issue',
            name='unique_open_issue_per_fingerprint_project',
        ),
        # 3. Add updated constraint with project__isnull=False condition
        migrations.AddConstraint(
            model_name='issue',
            constraint=models.UniqueConstraint(
                fields=['fingerprint', 'project'],
                condition=models.Q(status__in=['OPEN', 'MUTED'], project__isnull=False),
                name='unique_open_issue_per_fingerprint_project',
            ),
        ),
        # 4. Add new constraint for null-project issues
        migrations.AddConstraint(
            model_name='issue',
            constraint=models.UniqueConstraint(
                fields=['fingerprint', 'organisation'],
                condition=models.Q(status__in=['OPEN', 'MUTED'], project__isnull=True),
                name='unique_open_issue_per_fingerprint_org',
            ),
        ),
        # 5. Widen fingerprint max_length from 64 to 70
        migrations.AlterField(
            model_name='issue',
            name='fingerprint',
            field=models.CharField(blank=True, db_index=True, default='', max_length=70),
        ),
    ]
