"""Add ``topology_mode`` field to ObservabilityIntegration.

Enables SerOps to build the right metric queries per deployment shape:
  * ``vm``         — node/host-level metrics (existing default; bare-metal, VMs)
  * ``kubernetes`` — container metrics aggregated by ``service_name``
                     (EKS / GKE / AKS)

Default ``vm`` preserves current behavior for existing integrations.
Users opt in to Kubernetes mode explicitly via the integration
settings API (or admin UI, once the frontend exposes the dropdown).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integrations', '0003_remove_promscale_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='observabilityintegration',
            name='topology_mode',
            field=models.CharField(
                choices=[
                    ('vm', 'VM / bare-metal (host-level metrics)'),
                    ('kubernetes', 'Kubernetes (container-level metrics aggregated by service)'),
                ],
                default='vm',
                help_text='Metric-query topology. Set to `kubernetes` for EKS/GKE/AKS integrations.',
                max_length=16,
            ),
        ),
    ]
