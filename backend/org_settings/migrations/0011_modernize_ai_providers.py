"""Modernize AI provider catalog (2026-08-30).

- Update default_model on every existing provider to a current-gen ID
  (the previous IDs were mid-2025 or older; OpenAI's ``gpt-3.5-turbo``
  and ``gpt-4`` both shut down 2026-10-23 and would 404 for new users).
- Flip Claude + OpenAI to ``is_active=True`` — their adapters have
  been implemented for some time; the ``is_active=False`` from the
  original seed was stale.
- Seed Ollama as a fifth catalog entry. It reuses ``GenericOpenAIAdapter``
  via Ollama's stable OpenAI-compat layer at ``/v1/`` — no new adapter
  file needed. Ollama needs no API key.
- Clear ``env_key_name`` / ``env_url_name`` values. The env-var fallback
  in ``ai_service.get_api_key_for_org`` was removed in this same commit;
  keeping those fields populated would advertise "set GOOGLE_API_KEY and
  it'll work", which is no longer true. Fields kept in the schema for
  audit-trail purposes but values reflect current behaviour.

Model IDs verified against provider docs 2026-08-30. If any prove stale
at ship time, patch the ``defaults`` dict below and re-run migrations.
"""

from django.db import migrations


PROVIDER_UPDATES = {
    'gemini': {
        'display_name': 'Google Gemini',
        'default_model': 'gemini-3.5-flash',
        'adapter_class': 'ai_model.adapters.gemini.GeminiAdapter',
        'api_base_url': '',
        'is_active': True,
        'requires_api_key': True,
        'is_system': True,
        'env_key_name': '',
        'env_url_name': '',
    },
    'deepseek': {
        'display_name': 'DeepSeek',
        'default_model': 'deepseek-v4-flash',
        'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
        'api_base_url': 'https://api.deepseek.com',
        'is_active': True,
        'requires_api_key': True,
        'is_system': True,
        'env_key_name': '',
        'env_url_name': '',
    },
    'claude': {
        'display_name': 'Anthropic Claude',
        'default_model': 'claude-sonnet-5',
        'adapter_class': 'ai_model.adapters.claude.ClaudeAdapter',
        'api_base_url': '',
        'is_active': True,
        'requires_api_key': True,
        'is_system': True,
        'env_key_name': '',
        'env_url_name': '',
    },
    'openai': {
        'display_name': 'OpenAI',
        'default_model': 'gpt-5.6-terra',
        'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
        'api_base_url': '',
        'is_active': True,
        'requires_api_key': True,
        'is_system': True,
        'env_key_name': '',
        'env_url_name': '',
    },
    'ollama': {
        'display_name': 'Ollama (Local)',
        'default_model': 'qwen3:8b',
        'adapter_class': 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
        'api_base_url': 'http://localhost:11434/v1/',
        'is_active': True,
        'requires_api_key': False,
        'is_system': True,
        'env_key_name': '',
        'env_url_name': '',
    },
}


def modernize_providers(apps, schema_editor):
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')

    for name, defaults in PROVIDER_UPDATES.items():
        AIModelProvider.objects.update_or_create(
            name=name,
            defaults=defaults,
        )


def reverse_modernize(apps, schema_editor):
    """Best-effort reverse to the pre-migration state.

    Ollama row is deleted; other providers are reset to the last known
    mid-2025 defaults so a downgrade doesn't leave the DB advertising
    2026-only model IDs.
    """
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')

    legacy = {
        'gemini': {'default_model': 'gemini-2.5-flash', 'is_active': True},
        'deepseek': {'default_model': 'deepseek-chat', 'is_active': True},
        'claude': {'default_model': 'claude-3-sonnet', 'is_active': False},
        'openai': {'default_model': 'gpt-4', 'is_active': False},
    }

    for name, defaults in legacy.items():
        AIModelProvider.objects.filter(name=name).update(**defaults)

    AIModelProvider.objects.filter(name='ollama').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0010_issuesettings_memory_enabled_and_more'),
    ]

    operations = [
        migrations.RunPython(modernize_providers, reverse_modernize),
    ]
