"""CodeChange is unique per organisation (security review 2026-11, finding 2).

Rows unique on (provider, project_id, commit_sha) are also unique once the
organisation is added, so this needs no data change.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('Organisations', '0001_initial'),
        ('providers', '0017_gitops_integration_types'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='codechange',
            unique_together={('organisation', 'provider', 'project_id', 'commit_sha')},
        ),
    ]
