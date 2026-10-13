"""
Re-encrypt Jenkins api_token fields.

Previously, 'api_token' was not in the sensitive_fields set so it was stored
in plaintext inside the credentials JSON. This migration decrypts all credentials
and re-encrypts them so that api_token is now encrypted.
"""

from django.db import migrations


def reencrypt_jenkins_credentials(apps, schema_editor):
    """Decrypt and re-encrypt all Jenkins ProviderIntegration credentials."""
    ProviderIntegration = apps.get_model('providers', 'ProviderIntegration')

    for integration in ProviderIntegration.objects.filter(provider_type='jenkins'):
        creds = integration.credentials
        if not creds:
            continue

        # Import encryption functions at runtime
        from providers.encryption import decrypt_credentials, encrypt_credentials

        # Decrypt (handles _encrypted marker)
        decrypted = decrypt_credentials(creds)

        # Re-encrypt (now includes api_token in sensitive_fields)
        integration.credentials = encrypt_credentials(decrypted)
        integration.save(update_fields=['credentials'])


def noop(apps, schema_editor):
    """Reverse is a no-op — tokens remain encrypted."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('providers', '0012_add_job_error_summary'),
    ]

    operations = [
        migrations.RunPython(reencrypt_jenkins_credentials, noop),
    ]
