# Generated migration for role system update
# Renames devops/developer → user, keeps admin as-is

from django.db import migrations, models


def migrate_roles_forward(apps, schema_editor):
    """Migrate old roles to new role system."""
    User = apps.get_model('Users', 'User')
    
    # Rename devops and developer to user
    updated = User.objects.filter(role__in=['devops', 'developer']).update(role='user')
    print(f"Migrated {updated} users from devops/developer to user role")
    
    # admin stays as admin (no change needed)


def migrate_roles_backward(apps, schema_editor):
    """Rollback: convert user back to developer (safest default)."""
    User = apps.get_model('Users', 'User')
    
    # Convert user back to developer
    User.objects.filter(role='user').update(role='developer')
    
    # Convert viewer to developer (viewer didn't exist before)
    User.objects.filter(role='viewer').update(role='developer')


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0005_remove_securitysettings_sso_config_and_more'),
    ]

    operations = [
        # First, update existing data to new role values
        migrations.RunPython(migrate_roles_forward, migrate_roles_backward),
        
        # Then, alter the field to use new choices
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[('viewer', 'viewer'), ('user', 'user'), ('admin', 'admin')],
                default='viewer',
                max_length=255
            ),
        ),
    ]
