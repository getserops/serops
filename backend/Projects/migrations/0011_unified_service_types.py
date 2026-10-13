# Generated for unified service model (fresh database)
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Add subtype field and update service_type to 3 unified types.
    For fresh database - no data migration needed.
    """

    dependencies = [
        ('Projects', '0010_cicdbinding_scmbinding'),
    ]

    operations = [
        # Add subtype field
        migrations.AddField(
            model_name='projectservice',
            name='subtype',
            field=models.CharField(
                blank=True, 
                default='', 
                help_text='Optional subtype (e.g., database, cache, queue, backend, frontend)', 
                max_length=50
            ),
        ),
        
        # Update service_type choices and default
        migrations.AlterField(
            model_name='projectservice',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('application', 'Application'),
                    ('infrastructure', 'Infrastructure'),
                    ('custom', 'Custom'),
                ],
                default='application',
                max_length=20,
            ),
        ),
    ]
