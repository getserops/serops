"""
Data migration to seed initial AI model providers.
"""

from django.db import migrations


def seed_ai_providers(apps, schema_editor):
    """Create initial AI model providers."""
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
    
    providers = [
        {
            'name': 'gemini',
            'display_name': 'Google Gemini',
            'is_active': True,
            'requires_api_key': True,
            'default_model': 'gemini-2.5-flash',
        },
        {
            'name': 'deepseek',
            'display_name': 'DeepSeek',
            'is_active': True,
            'requires_api_key': True,
            'default_model': 'deepseek-chat',
        },
        {
            'name': 'claude',
            'display_name': 'Anthropic Claude',
            'is_active': False,  # Not yet implemented
            'requires_api_key': True,
            'default_model': 'claude-3-sonnet',
        },
        {
            'name': 'openai',
            'display_name': 'OpenAI GPT',
            'is_active': False,  # Not yet implemented
            'requires_api_key': True,
            'default_model': 'gpt-4',
        },
    ]
    
    for provider_data in providers:
        AIModelProvider.objects.get_or_create(
            name=provider_data['name'],
            defaults=provider_data
        )


def reverse_seed(apps, schema_editor):
    """Remove seeded providers (optional)."""
    pass


class Migration(migrations.Migration):
    
    dependencies = [
        ('org_settings', '0001_initial'),
    ]
    
    operations = [
        migrations.RunPython(seed_ai_providers, reverse_seed),
    ]
