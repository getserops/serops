"""Sentinel active mode becomes the default (external review of v1.2.13).

Shadow mode as the default meant an AI call for every window on a fresh
install. New rows now default to active mode, and so do orgs with no row at
all (``Data.sentinel._get_sentinel_config``).

Existing rows: a row is created the first time anyone OPENS Settings →
Sentinel (``SentinelConfigView.get`` does ``get_or_create``), so a stored
``active_mode=False`` usually means "somebody looked", not "somebody chose
shadow mode". Only a save marks a choice: every save bumps ``updated_at``
(``auto_now``), while a row nobody ever saved keeps ``updated_at`` equal to
``created_at`` give or take the microseconds between the two ``now()``
calls. So rows still in shadow mode and never saved move to active mode,
like the orgs that never opened the page; any row an admin saved keeps its
mode, whatever it is.
"""

from datetime import timedelta

from django.db import migrations, models

# Wide enough for the gap between auto_now_add and auto_now on one INSERT,
# far narrower than any human opening the page and then saving it.
_NEVER_SAVED = timedelta(seconds=1)


def activate_never_saved_rows(apps, schema_editor):
    SentinelConfig = apps.get_model('org_settings', 'SentinelConfig')
    ids = [
        row.pk for row in SentinelConfig.objects.filter(active_mode=False).only(
            'pk', 'created_at', 'updated_at')
        if abs(row.updated_at - row.created_at) < _NEVER_SAVED
    ]
    # .update() so updated_at stays as it was: this is not an admin's save.
    SentinelConfig.objects.filter(pk__in=ids).update(active_mode=True)


class Migration(migrations.Migration):

    dependencies = [
        ('org_settings', '0020_alter_aimodelprovider_env_key_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sentinelconfig',
            name='active_mode',
            field=models.BooleanField(default=True, help_text='When True, quiet batches skip AI analysis. When False, shadow mode.'),
        ),
        # Not reversible to the old values: which rows were flipped is not
        # recorded, and shadow mode was never anyone's choice for them.
        migrations.RunPython(activate_never_saved_rows, migrations.RunPython.noop),
    ]
