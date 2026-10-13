# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("Data", "0034_retentionpolicy_batch_generation_interval"),
    ]

    operations = [
        migrations.AlterField(
            model_name="retentionpolicy",
            name="batch_generation_interval",
            field=models.IntegerField(
                choices=[
                    (5, "5 minutes"),
                    (10, "10 minutes"),
                    (15, "15 minutes"),
                    (20, "20 minutes"),
                    (30, "30 minutes"),
                    (45, "45 minutes"),
                    (60, "1 hour"),
                    (120, "2 hours"),
                    (240, "4 hours"),
                    (360, "6 hours"),
                    (720, "12 hours"),
                ],
                default=15,
                help_text="How often to generate log/metric batches (in minutes)",
            ),
        ),
    ]
