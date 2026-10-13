"""
Migration to make AI providers fully DB-driven:
- Remove choices constraint from name field
- Add env_key_name, env_url_name, is_system fields
- Populate existing rows with correct adapter_class, env vars, and is_system flag
"""

from django.db import migrations, models


def populate_provider_fields(apps, schema_editor):
    """Set adapter_class, env_key_name, env_url_name, is_system for existing providers."""
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')

    provider_config = {
        'gemini': {
            'adapter_class': 'ai_model.adapters.gemini.GeminiAdapter',
            'env_key_name': 'GOOGLE_API_KEY',
            'env_url_name': '',
            'is_system': True,
        },
        'deepseek': {
            'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            'env_key_name': 'DEEPSEEK_API_KEY',
            'env_url_name': 'DEEPSEEK_API_URL',
            'is_system': True,
        },
        'claude': {
            'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
            'env_key_name': 'ANTHROPIC_API_KEY',
            'env_url_name': '',
            'is_system': True,
            'is_active': True,
            'default_model': 'claude-sonnet-4-20250514',
        },
        'openai': {
            'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
            'env_key_name': 'OPENAI_API_KEY',
            'env_url_name': '',
            'is_system': True,
            'is_active': True,
            'default_model': 'gpt-4',
        },
    }

    for name, config in provider_config.items():
        try:
            provider = AIModelProvider.objects.get(name=name)
            provider.adapter_class = config['adapter_class']
            provider.env_key_name = config['env_key_name']
            provider.env_url_name = config['env_url_name']
            provider.is_system = config['is_system']
            if 'is_active' in config:
                provider.is_active = config['is_active']
            if 'default_model' in config:
                provider.default_model = config['default_model']
            provider.save()
        except AIModelProvider.DoesNotExist:
            pass


def reverse_populate(apps, schema_editor):
    """Reverse: reset new fields to defaults."""
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
    AIModelProvider.objects.all().update(
        env_key_name='',
        env_url_name='',
        is_system=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0008_system_mail_settings_and_sender_name'),
    ]

    operations = [
        # Remove choices from name field
        migrations.AlterField(
            model_name='aimodelprovider',
            name='name',
            field=models.CharField(max_length=50, unique=True),
        ),
        # Add new fields
        migrations.AddField(
            model_name='aimodelprovider',
            name='env_key_name',
            field=models.CharField(
                blank=True, default='', max_length=100,
                help_text='Env var name for API key (e.g. GOOGLE_API_KEY)',
            ),
        ),
        migrations.AddField(
            model_name='aimodelprovider',
            name='env_url_name',
            field=models.CharField(
                blank=True, default='', max_length=100,
                help_text='Env var name for base URL (e.g. DEEPSEEK_API_URL)',
            ),
        ),
        migrations.AddField(
            model_name='aimodelprovider',
            name='is_system',
            field=models.BooleanField(
                default=False,
                help_text='System providers cannot be deleted by users',
            ),
        ),
        # Populate existing rows
        migrations.RunPython(populate_provider_fields, reverse_populate),
    ]
