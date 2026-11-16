from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0061_auditlog_stream_actions'),
    ]

    operations = [
        migrations.AddField(
            model_name='alertevent',
            name='starts_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='alertevent',
            name='labels',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='alertevent',
            name='match_status',
            field=models.CharField(blank=True, choices=[('matched', 'Matched to a project'), ('unmatched', 'Matched no service: not analysed'), ('repeat', 'Repeat of an alert already analysed')], default='', max_length=16),
        ),
        migrations.AddField(
            model_name='alertevent',
            name='match_detail',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]
