# Generated migration to rename app from 'Gitlab' to 'providers'
from django.db import migrations


def rename_app_in_db(apps, schema_editor):
    """Rename app from 'Gitlab' to 'providers' in Django system tables."""
    with schema_editor.connection.cursor() as cursor:
        # Update django_migrations table
        cursor.execute(
            "UPDATE django_migrations SET app = 'providers' WHERE app = 'Gitlab'"
        )
        # Update django_content_type table
        cursor.execute(
            "UPDATE django_content_type SET app_label = 'providers' WHERE app_label = 'Gitlab'"
        )


def reverse_rename(apps, schema_editor):
    """Reverse: rename app from 'providers' back to 'Gitlab'."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "UPDATE django_migrations SET app = 'Gitlab' WHERE app = 'providers'"
        )
        cursor.execute(
            "UPDATE django_content_type SET app_label = 'Gitlab' WHERE app_label = 'providers'"
        )


class Migration(migrations.Migration):
    """
    Rename app from 'Gitlab' to 'providers'.
    
    This migration updates Django's system tables to reflect the new app name.
    Must run after renaming the folder and updating all references.
    """
    
    dependencies = [
        ('providers', '0006_phase2_multi_provider'),
        ('contenttypes', '__latest__'),  # Ensure django_content_type table exists
    ]
    
    operations = [
        migrations.RunPython(rename_app_in_db, reverse_rename),
    ]
