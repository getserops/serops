# Adds AI evidence chain (reasoning) and confidence rating to Issue.
# Populated by the batch-analysis prompt and rendered on the frontend
# so users see *why* the AI reached its root_cause, and how confident
# it is.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0039_auditlog_gdpr_action_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='reasoning',
            field=models.TextField(
                blank=True,
                null=True,
                help_text=(
                    "Step-by-step evidence chain the AI followed "
                    "(1. observed, 2. checked, 3. concluded)."
                ),
            ),
        ),
        migrations.AddField(
            model_name='issue',
            name='confidence',
            field=models.CharField(
                choices=[
                    ('LOW', 'Low'),
                    ('MEDIUM', 'Medium'),
                    ('HIGH', 'High'),
                    ('UNKNOWN', 'Unknown'),
                ],
                default='UNKNOWN',
                db_index=True,
                max_length=10,
                help_text=(
                    "How confident the AI is in this root cause. "
                    "UNKNOWN when the AI did not report a confidence."
                ),
            ),
        ),
    ]
