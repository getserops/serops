from django.db import migrations, models


class Migration(migrations.Migration):
    """A Google service-account key (~2.3k characters, ~3.2k encrypted) did
    not fit the 1000-character password column."""

    dependencies = [
        ('integrations', '0010_encrypt_extra_config_secrets'),
    ]

    operations = [
        migrations.AlterField(
            model_name='observabilityintegration',
            name='password',
            field=models.TextField(blank=True, help_text='Encrypted at rest via Fernet'),
        ),
    ]
