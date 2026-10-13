"""Add extra_config JSONField to OrganisationAPIKey (E31-8).

Provider-specific config bag for auth quirks like Anthropic's
workspace_id. Previously, Anthropic workspace-scoped keys failed
with HTTP 400 because SerOps' client didn't send the
``anthropic-workspace-id`` header — surfaces in the UI as
"FAILED (AUTH_ERROR)". This field is the storage side of the fix;
the ClaudeAdapter reads it and sets the header.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0017_refresh_ai_provider_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisationapikey',
            name='extra_config',
            field=models.JSONField(
                default=dict, blank=True,
                help_text='Provider-specific extras (e.g., anthropic workspace_id).',
            ),
        ),
    ]
