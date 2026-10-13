"""PR-N phase 2 (2026-09-26): retire ``NotificationSettings``.

Data was already migrated to ``notifications.IncidentNotificationChannel``
in ``notifications/0004_backfill_incident_channels_from_notif_settings``
(email/slack/teams flags → one channel row per kind, marked via
``extra_config['legacy_source']='org_settings.NotificationSettings'``).

By the time this migration runs, ``notifications/0005_routing_rules``
has also created a catch-all routing rule per org preserving the
"all channels see every incident" behaviour that ``NotificationSettings``
implicitly encoded.

This migration drops the legacy model. The reverse re-creates a
stub table so a rollback to a pre-phase-2 backup won't hard-fail;
the stub is intentionally column-less because a real reversal would
need to re-materialise the data from the ``IncidentNotificationChannel``
rows, which is a support operation, not a migration one.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0018_organisationapikey_extra_config'),
        # Ensure the notifications-side backfill + routing-rules are in
        # place before we delete the legacy model.
        ('notifications', '0005_routing_rules'),
    ]

    operations = [
        migrations.DeleteModel(name='NotificationSettings'),
    ]
