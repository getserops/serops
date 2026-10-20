import secrets

from django.db import migrations


def backfill(apps, schema_editor):
    """Give every secret-less SCM binding a webhook secret.

    The receiver now fails closed when a binding has no secret (2026-10-20
    security review). Any binding created before this had an empty secret
    and accepted unauthenticated payloads; backfilling makes them
    well-formed. The webhook on the provider side must be re-pointed at
    the new secret via Setup Webhook.
    """
    SCMBinding = apps.get_model('Projects', 'SCMBinding')
    for binding in SCMBinding.objects.filter(webhook_secret=''):
        binding.webhook_secret = secrets.token_hex(32)
        binding.save(update_fields=['webhook_secret'])


class Migration(migrations.Migration):
    dependencies = [('Projects', '0014_seed_project_deployments')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
