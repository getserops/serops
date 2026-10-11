"""
Data migration: Backfill Issue.organisation from project.organisation for existing issues.
"""

from django.db import migrations


def backfill_organisation(apps, schema_editor):
    # Use raw SQL for efficient bulk update across join
    schema_editor.execute(
        """
        UPDATE "Data_issue" i
        SET organisation_id = p.organisation_id
        FROM "Projects_project" p
        WHERE i.project_id = p.id
          AND i.organisation_id IS NULL
          AND i.project_id IS NOT NULL
        """
    )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0029_issue_org_fk_and_fingerprint_versioning'),
    ]

    operations = [
        migrations.RunPython(backfill_organisation, noop),
    ]
