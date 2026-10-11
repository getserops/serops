from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('providers', '0013_reencrypt_jenkins_api_tokens'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gitlabproject',
            name='access_token',
            field=models.CharField(max_length=512),
        ),
    ]
