"""PR-N phase 2 (2026-09-26): routing rules table + catch-all backfill.

Two operations, wrapped in one migration:

1. Create ``NotificationRoutingRule`` (the Alertmanager-style route
   table, see ``notifications/models.py``).

2. Backfill one catch-all rule per organisation that has at least
   one ``IncidentNotificationChannel`` — matches every event/severity
   and targets every active channel. This preserves 2026-09-25
   behaviour (all channels see every incident) on upgrade day; the
   operator narrows it in the UI later.

Retirement of ``org_settings.NotificationSettings`` is a separate
migration in the ``org_settings`` app (``0019_retire_notification_settings``),
sequenced AFTER this one so the routing-rules backfill runs against
the current channel set before the legacy model is dropped.
"""
from __future__ import annotations

from django.db import migrations, models
import django.db.models.deletion


def backfill_catch_all_rules(apps, schema_editor):
    Rule = apps.get_model('notifications', 'NotificationRoutingRule')
    Channel = apps.get_model('notifications', 'IncidentNotificationChannel')
    Organisation = apps.get_model('Organisations', 'Organisations')

    for org in Organisation.objects.all().iterator():
        channels = list(
            Channel.objects.filter(organisation=org, is_active=True),
        )
        if not channels:
            continue
        rule, created = Rule.objects.get_or_create(
            organisation=org, name='Catch-all (auto-created 2026-09-26)',
            defaults={
                'is_active': True,
                'min_severity': '',
                'environments': [],
                'services': [],
                'event_types': [],
                'priority': 1000,
            },
        )
        if created:
            rule.targets.set(channels)


def unbackfill_catch_all_rules(apps, schema_editor):
    Rule = apps.get_model('notifications', 'NotificationRoutingRule')
    Rule.objects.filter(
        name='Catch-all (auto-created 2026-09-26)',
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0004_backfill_incident_channels_from_notif_settings'),
        # Depend on the latest ``org_settings`` migration so the
        # DELETE below is against the current-shape NotificationSettings.
        ('org_settings', '0018_organisationapikey_extra_config'),
        ('Organisations', '0011_alert_ingest_secret'),
    ]

    operations = [
        # 1. Routing rules table.
        migrations.CreateModel(
            name='NotificationRoutingRule',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True,
                                        serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('min_severity', models.CharField(blank=True, default='',
                                                   max_length=16)),
                ('environments', models.JSONField(blank=True, default=list)),
                ('services', models.JSONField(blank=True, default=list)),
                ('event_types', models.JSONField(blank=True, default=list)),
                ('suppress_for_minutes', models.PositiveIntegerField(default=0)),
                ('escalate_after_minutes', models.PositiveIntegerField(default=0)),
                ('priority', models.PositiveIntegerField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='routing_rules',
                    to='Organisations.organisations',
                )),
                ('targets', models.ManyToManyField(
                    related_name='routing_rules',
                    to='notifications.incidentnotificationchannel',
                )),
            ],
            options={
                'db_table': 'notifications_routing_rule',
                'ordering': ['priority', 'name'],
                'indexes': [
                    models.Index(fields=['organisation', 'is_active'],
                                 name='routing_rule_org_active_idx'),
                ],
            },
        ),

        # 2. Backfill catch-all rule per org.
        migrations.RunPython(backfill_catch_all_rules, reverse_code=unbackfill_catch_all_rules),
    ]
