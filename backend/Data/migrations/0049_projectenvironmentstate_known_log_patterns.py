from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0048_investigations'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectenvironmentstate',
            name='known_log_patterns',
            field=models.JSONField(default=dict),
        ),
    ]
