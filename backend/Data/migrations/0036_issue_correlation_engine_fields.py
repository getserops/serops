from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Data", "0035_change_batch_interval_default_to_15"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="correlation_confidence",
            field=models.CharField(
                blank=True,
                choices=[("HIGH", "High"), ("MEDIUM", "Medium"), ("LOW", "Low"), ("", "None")],
                default="",
                help_text="Confidence level from correlation engine (HIGH/MEDIUM/LOW)",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="issue",
            name="metric_anomaly_type",
            field=models.CharField(
                blank=True,
                choices=[("spike", "Spike"), ("sustained_high", "Sustained High"), ("", "None")],
                default="",
                help_text="Type of metric anomaly: spike or sustained_high",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="issue",
            name="correlation_details",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Full matched correlation data from engine (peak value, duration, commit links, etc.)",
            ),
        ),
    ]
