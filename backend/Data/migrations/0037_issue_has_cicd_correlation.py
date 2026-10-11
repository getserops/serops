from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0036_issue_correlation_engine_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='issue',
            name='has_cicd_correlation',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text='Whether this issue correlates with a CI/CD pipeline failure',
            ),
        ),
    ]
