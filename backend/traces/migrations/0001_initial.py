"""Initial migration for the traces app — Trace, Span, IngestKey."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('Organisations', '0001_initial'),
        ('Users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='IngestKey',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('name', models.CharField(
                    help_text='Human-readable label (e.g. "prod k8s cluster", "staging OTEL Collector").',
                    max_length=100,
                )),
                ('key_hash', models.CharField(db_index=True, max_length=64, unique=True)),
                ('key_prefix', models.CharField(
                    help_text='First few chars of the key for identification without exposing the whole thing.',
                    max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='+',
                    to='Users.user',
                )),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='ingest_keys',
                    to='Organisations.organisations',
                )),
            ],
            options={
                'db_table': 'traces_ingest_key',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['organisation', 'is_active'],
                                 name='ingestkey_org_active_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='Trace',
            fields=[
                ('trace_id', models.CharField(max_length=32, primary_key=True, serialize=False)),
                ('root_service_name', models.CharField(blank=True, default='', max_length=255)),
                ('root_operation', models.CharField(blank=True, default='', max_length=255)),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('duration_ms', models.IntegerField(default=0)),
                ('span_count', models.IntegerField(default=0)),
                ('error_span_count', models.IntegerField(default=0)),
                ('status_code', models.CharField(blank=True, default='UNSET', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('organisation', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='traces',
                    to='Organisations.organisations',
                )),
            ],
            options={
                'db_table': 'traces_trace',
                'ordering': ['-start_time'],
                'indexes': [
                    models.Index(fields=['organisation', '-start_time'], name='trace_org_start_idx'),
                    models.Index(fields=['organisation', 'root_service_name', '-start_time'],
                                 name='trace_org_svc_start_idx'),
                    models.Index(fields=['organisation', 'status_code', '-start_time'],
                                 name='trace_org_status_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='Span',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('span_id', models.CharField(max_length=16)),
                ('parent_span_id', models.CharField(blank=True, default='', max_length=16)),
                ('service_name', models.CharField(blank=True, db_index=True, default='', max_length=255)),
                ('operation_name', models.CharField(max_length=255)),
                ('kind', models.CharField(
                    blank=True, default='INTERNAL',
                    choices=[('INTERNAL', 'Internal'), ('SERVER', 'Server'),
                             ('CLIENT', 'Client'), ('PRODUCER', 'Producer'),
                             ('CONSUMER', 'Consumer')],
                    max_length=16,
                )),
                ('start_time', models.DateTimeField()),
                ('end_time', models.DateTimeField()),
                ('duration_ms', models.IntegerField()),
                ('status_code', models.CharField(
                    blank=True, default='UNSET',
                    choices=[('UNSET', 'Unset'), ('OK', 'OK'), ('ERROR', 'Error')],
                    max_length=16,
                )),
                ('status_message', models.CharField(blank=True, default='', max_length=500)),
                ('attributes', models.JSONField(blank=True, default=dict)),
                ('events', models.JSONField(blank=True, default=list)),
                ('trace', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='spans',
                    to='traces.trace',
                )),
            ],
            options={
                'db_table': 'traces_span',
                'ordering': ['start_time'],
                'unique_together': {('trace', 'span_id')},
                'indexes': [
                    models.Index(fields=['trace', 'start_time'], name='span_trace_start_idx'),
                    models.Index(fields=['service_name', '-start_time'], name='span_svc_start_idx'),
                ],
            },
        ),
    ]
