"""Data migration — populate IntegrationScope from existing ObservabilityIntegration.cluster (Batch 48).

Every existing integration gets a matching IntegrationScope row with:
  * ``cluster`` = the integration's current cluster FK (mirror)
  * ``environment`` = '' (wildcard — pre-Batch 48 integrations weren't env-scoped)
  * ``region`` = '' (wildcard)
  * ``namespace`` = '' (wildcard)

Also seeds ``priority_tier='primary'`` — already the default so nothing
extra to do here, but noting for readers.

Idempotent via get_or_create. Reverse deletes all IntegrationScope rows.
"""

from django.db import migrations


def seed_scopes(apps, schema_editor):
    ObservabilityIntegration = apps.get_model('integrations', 'ObservabilityIntegration')
    IntegrationScope = apps.get_model('integrations', 'IntegrationScope')

    created_count = 0
    for integ in ObservabilityIntegration.objects.all().iterator(chunk_size=500):
        _, was_created = IntegrationScope.objects.get_or_create(
            integration=integ,
            defaults={
                'cluster': integ.cluster,
                'environment': '',
                'region': '',
                'namespace': '',
            },
        )
        if was_created:
            created_count += 1

    if created_count:
        print(f'[Batch 48 migration] Created {created_count} IntegrationScope row(s).')


def unseed_scopes(apps, schema_editor):
    IntegrationScope = apps.get_model('integrations', 'IntegrationScope')
    IntegrationScope.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0008_integrationscope_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_scopes, reverse_code=unseed_scopes),
    ]
