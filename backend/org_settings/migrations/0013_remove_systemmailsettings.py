"""Drop the SystemMailSettings singleton — SMTP is now env-only.

2026-09-01: SerOps switched to the Grafana model for SMTP configuration.
The UI-editable ``SystemMailSettings`` row is gone; ``EMAIL_HOST`` and
friends come exclusively from environment variables. Verify config with
``python manage.py check_smtp <recipient>``.

Upgrading a live install:
  1. On the old backend, run
        docker exec serops_backend python manage.py print_smtp_env
     (available in the v1.x deprecation release) OR grab values from
     the Settings → Email page before upgrading.
  2. Paste values into your .env as EMAIL_HOST, EMAIL_PORT,
     EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, EMAIL_USE_TLS,
     DEFAULT_FROM_EMAIL.
  3. Restart the backend. Old DB row will be dropped by this migration.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0012_ai_provider_pricing'),
    ]

    operations = [
        migrations.DeleteModel(
            name='SystemMailSettings',
        ),
    ]
