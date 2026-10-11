"""Refresh AIModelProvider.default_model values (E1-2 fix, 2026-09-09).

Migration 0014 seeded default_model with values that were current at
authoring time but drift as providers deprecate model IDs. Google
already removed `gemini-2.0-flash` (used earlier in dev) and
`gemini-3.5-flash` returns HTTP 404 "no longer available, use
gemini-3.6-flash" — so a fresh self-hoster following the quick-start
docs hit a broken first AI call.

Fix: idempotent update to current-generation model IDs verified
against the respective provider consoles on 2026-09-09. Only touches
`default_model`; leaves everything else alone.

Class of issue applies to any hosted AI provider (they all cycle
models). Long-term: consider fetching the current default from each
provider's list-models endpoint on install rather than hardcoding.
"""

from django.db import migrations


# Verified against provider console 2026-09-09. Only touch what we've
# actually tested — other providers' default_model values may be
# current or stale but that's a separate audit (Q-item).
CURRENT_DEFAULTS = {
    "gemini": "gemini-3.6-flash",   # was gemini-3.5-flash (Google returns 404 with "use gemini-3.6-flash" hint)
}


def refresh_default_models(apps, schema_editor):
    AIModelProvider = apps.get_model("org_settings", "AIModelProvider")
    updated = 0
    for name, new_default in CURRENT_DEFAULTS.items():
        n = AIModelProvider.objects.filter(name=name).exclude(
            default_model=new_default,
        ).update(default_model=new_default)
        if n:
            print(f"[E1-2 fix] {name}.default_model → {new_default}")
        updated += n
    if updated:
        print(f"[E1-2 fix] refreshed {updated} provider default_model value(s)")


def noop_reverse(apps, schema_editor):
    """Reverse: no-op. We don't restore stale model IDs on rollback
    — those IDs were broken to begin with."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("org_settings", "0016_sentinelconfig_pre_creation_gate_enabled"),
    ]

    operations = [
        migrations.RunPython(refresh_default_models, reverse_code=noop_reverse),
    ]
