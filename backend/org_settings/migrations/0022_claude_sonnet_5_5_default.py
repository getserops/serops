"""New installs default the Claude provider to Sonnet 5.5.

Sonnet 5.5 (2026-11) replaces Sonnet 5 as Anthropic's balanced tier at
the same price. The Claude provider row is shared, so changing its
model changes it for every organisation using Claude: the row moves
only while no organisation has Claude as its primary or fallback
provider (a new install, or one where nobody picked Claude), and only
from the seeded ``claude-sonnet-5``. A row an admin edited, or one an
organisation already runs on, keeps its model.
"""

from django.db import migrations
from django.db.models import Q


def forwards(apps, schema_editor):
    AIModelProvider = apps.get_model('org_settings', 'AIModelProvider')
    OrganisationAISettings = apps.get_model('org_settings', 'OrganisationAISettings')
    row = AIModelProvider.objects.filter(name='claude', default_model='claude-sonnet-5').first()
    if row is None:
        return
    if OrganisationAISettings.objects.filter(Q(default_provider=row) | Q(fallback_provider=row)).exists():
        return
    row.default_model = 'claude-sonnet-5-5'
    row.save(update_fields=['default_model'])


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0021_sentinel_active_mode_default'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
