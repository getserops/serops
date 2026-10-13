"""Add per-provider pricing fields + seed current public list prices.

Prices moved from a hardcoded dict in ``ai_model/usage_tracking.py``
(``PRICING_PER_MILLION_TOKENS``) to columns on ``AIModelProvider`` so
they can never drift from the model IDs they price. The old dict was
already stale — it referenced ``gemini-2.5-flash`` and
``claude-sonnet-4-20250514`` after Day 1 updated the seed defaults to
``gemini-3.5-flash`` and ``claude-sonnet-5``, so token cost reports
were incorrect on every deploy after 2026-08-30.

List prices sourced from provider public pricing pages, mid-2026.
Kept in sync with the model IDs seeded in ``0011_modernize_ai_providers``.
Update these values by running the ``reseed`` operation of this
migration OR by editing directly in the admin — same source of truth
either way.
"""

from decimal import Decimal
from django.db import migrations, models


# USD per 1M tokens, current gen models, mid-2026.
# ``price_input`` / ``price_output`` follow provider pricing pages.
# Ollama is $0 (local inference); DeepSeek is intentionally low to
# match its cost-leader positioning.
PROVIDER_PRICING = {
    'gemini':   {'input': Decimal('0.075'), 'output': Decimal('0.300')},
    'claude':   {'input': Decimal('2.000'), 'output': Decimal('10.000')},
    'openai':   {'input': Decimal('2.000'), 'output': Decimal('12.000')},
    'deepseek': {'input': Decimal('0.014'), 'output': Decimal('0.028')},
    'ollama':   {'input': Decimal('0.000'), 'output': Decimal('0.000')},
}


def seed_prices(apps, schema_editor):
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
    for name, prices in PROVIDER_PRICING.items():
        AIModelProvider.objects.filter(name=name).update(
            price_input_per_million=prices['input'],
            price_output_per_million=prices['output'],
        )


def unseed_prices(apps, schema_editor):
    """Best-effort reverse: reset to 0.

    Doesn't restore the old hardcoded values because the whole point
    of the migration was to make that dict wrong-by-construction.
    """
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
    AIModelProvider.objects.all().update(
        price_input_per_million=Decimal('0'),
        price_output_per_million=Decimal('0'),
    )


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0011_modernize_ai_providers'),
    ]

    operations = [
        migrations.AddField(
            model_name='aimodelprovider',
            name='price_input_per_million',
            field=models.DecimalField(
                decimal_places=6, default=0, max_digits=10,
                help_text='USD per 1M input tokens (public list price).',
            ),
        ),
        migrations.AddField(
            model_name='aimodelprovider',
            name='price_output_per_million',
            field=models.DecimalField(
                decimal_places=6, default=0, max_digits=10,
                help_text='USD per 1M output tokens (public list price).',
            ),
        ),
        migrations.RunPython(seed_prices, unseed_prices),
    ]
