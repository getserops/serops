# Generated for Past-Incident Memory feature.
# Adds a composite index used by Data.memory.find_past_memories() to look up
# resolved issues by project + environment, ordered by most recent resolution.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0037_issue_has_cicd_correlation'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='issue',
            index=models.Index(
                fields=['project', 'environment', 'status', '-resolved_at'],
                name='issue_memory_lookup_idx',
            ),
        ),
    ]
