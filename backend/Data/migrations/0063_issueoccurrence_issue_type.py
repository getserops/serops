from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Data', '0062_alertevent_starts_at_labels_match'),
    ]

    operations = [
        migrations.AddField(
            model_name='issueoccurrence',
            name='issue_type',
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
    ]
