# Adds the is_demo flag for the public read-only "Acme Cloud" demo org
# served on app.serops.ai. Only one organisation per deployment is
# expected to carry this flag.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Organisations', '0008_remove_organisations_plan_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisations',
            name='is_demo',
            field=models.BooleanField(
                default=False,
                db_index=True,
                help_text='True for the public demo org; data is regenerated nightly.',
            ),
        ),
    ]
