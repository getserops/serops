# Adds the is_demo flag for the public read-only demo identity served
# on app.serops.ai. Demo users are blocked from all unsafe HTTP methods
# by Middlewares.DemoUserMiddleware regardless of their RBAC role.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Users', '0008_securitysettings_saml_entity_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_demo',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text='True for the public demo user; blocked from all writes.',
            ),
        ),
    ]
