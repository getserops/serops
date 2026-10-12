"""Encrypt credentials that earlier versions stored in plain ``extra_config``.

Datadog's ``api_key``/``app_key``, bearer tokens and the other keys in
``SECRET_EXTRA_CONFIG_KEYS`` sat unencrypted in the database. From this
release the model encrypts them on save; this migration does the same for
rows saved before it. Historical models skip the custom ``save()``, so the
helper is called explicitly. Re-running it is safe: encrypted values are
recognised and left alone.
"""

from django.db import migrations


def encrypt_existing(apps, schema_editor):
    from integrations.models import encrypt_extra_config_secrets

    ObservabilityIntegration = apps.get_model('integrations', 'ObservabilityIntegration')
    for integration in ObservabilityIntegration.objects.exclude(extra_config={}):
        encrypted = encrypt_extra_config_secrets(integration.extra_config)
        if encrypted != integration.extra_config:
            integration.extra_config = encrypted
            integration.save(update_fields=['extra_config'])


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0009_seed_integration_scopes'),
    ]

    operations = [
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
