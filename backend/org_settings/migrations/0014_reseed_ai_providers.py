"""Re-seed AI provider catalog + list prices (Q1.2 fix).

Some environments have migration 0011 + 0012 marked as applied but
the ``AIModelProvider`` table is empty — a classic Django data-
migration drift where the RunPython operation ran before the target
schema existed (or was partially rolled back at some point) and
silent-failed. Django flagged the migration as applied and never
re-runs.

This migration re-runs BOTH the modernize (name → defaults) + the
pricing seed, idempotently. Safe on any DB in any state:

* Fresh DB — creates the rows.
* Correctly-seeded DB — ``update_or_create`` matches on ``name``
  and rewrites the defaults with the same values (no-op).
* Drifted DB — restores the missing rows.

Keep this migration idempotent forever. When a future prices
update lands, ship a NEW re-seed migration rather than editing
this one — that way rollback semantics stay predictable.
"""

from decimal import Decimal

from django.db import migrations


# Kept in sync with org_settings.migrations.0011 + 0012. Copied here
# so the migration is self-contained — if either source migration
# gets rewritten later, this one still runs.
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


PROVIDER_PRICING = {
    'gemini':   {'input': Decimal('0.075'), 'output': Decimal('0.300')},
    'claude':   {'input': Decimal('2.000'), 'output': Decimal('10.000')},
    'openai':   {'input': Decimal('2.000'), 'output': Decimal('12.000')},
    'deepseek': {'input': Decimal('0.014'), 'output': Decimal('0.028')},
    'ollama':   {'input': Decimal('0.000'), 'output': Decimal('0.000')},
}


def reseed_providers(apps, schema_editor):
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')

    for name, defaults in PROVIDER_UPDATES.items():
        AIModelProvider.objects.update_or_create(
            name=name, defaults=defaults,
        )

    for name, prices in PROVIDER_PRICING.items():
        AIModelProvider.objects.filter(name=name).update(
            price_input_per_million=prices['input'],
            price_output_per_million=prices['output'],
        )


def noop_reverse(apps, schema_editor):
    """Reversing this migration is a no-op — 0011 + 0012 own the
    original teardown semantics. We deliberately don't undo the seed
    here because doing so would leave the DB inconsistent."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0013_remove_systemmailsettings'),
    ]

    operations = [
        migrations.RunPython(reseed_providers, noop_reverse),
    ]
