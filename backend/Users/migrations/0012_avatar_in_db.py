import os
import secrets

from django.conf import settings
from django.db import migrations, models

AVATAR_MAX_SIDE = 128


def import_avatars(apps, schema_editor):
    """Copy avatars uploaded under the old file scheme into the database.

    Docker Compose kept them in its media volume; elsewhere the file is
    usually gone, and that user simply has no avatar any more.
    """
    from Utils.images import ImageRejected, to_small_png

    User = apps.get_model('Users', 'User')
    for user in User.objects.exclude(avatar__isnull=True).exclude(avatar=''):
        path = os.path.join(settings.MEDIA_ROOT, str(user.avatar))
        try:
            with open(path, 'rb') as fh:
                user.avatar_png = to_small_png(fh, AVATAR_MAX_SIDE)
        except (OSError, ImageRejected):
            continue
        user.avatar_key = secrets.token_hex(16)
        user.save(update_fields=['avatar_png', 'avatar_key'])


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0011_sso_oidc_only'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='avatar_key',
            field=models.CharField(blank=True, db_index=True, default='', max_length=32),
        ),
        migrations.AddField(
            model_name='user',
            name='avatar_png',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.RunPython(import_avatars, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='user',
            name='avatar',
        ),
    ]
