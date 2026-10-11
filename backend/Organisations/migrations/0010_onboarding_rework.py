"""Rework OnboardingStatus for the computed-state wizard (item #11).

Schema:
- Add ``skipped_steps`` JSONField (default list).
- Widen ``current_step`` max_length from 30 → 40 (new step names like
  ``waiting_for_first_analysis`` don't fit the old bound).
- Update ``current_step`` choices to the new 9-step enum.

Data:
- Rename legacy step names in ``current_step`` and ``completed_steps``:
    ``connect_integration``  → ``connect_observability``
    ``configure_logs``       → dropped (subsumed by observability)
- Any row whose ``current_step`` was set to a step that no longer
  exists (``configure_logs``, or unexpected values) is reset to
  ``welcome`` — the next status GET calls ``refresh_and_advance()``
  which will land the cursor on the correct step from real DB state.
- ``is_completed`` is intentionally NOT recomputed here. The next
  status read will run ``refresh_and_advance()`` and honestly
  re-derive it. If a legacy org had ``is_completed=True`` but doesn't
  pass the new required-step check (e.g. no AI provider configured),
  the wizard will reappear — that's the correct behaviour, because
  under the new definition of "activated" they aren't.
"""

from django.db import migrations, models


NEW_STEP_CHOICES = [
    ('welcome', 'Welcome'),
    ('connect_ai_provider', 'Choose AI Model'),
    ('connect_observability', 'Connect Observability'),
    ('create_project', 'Create Project'),
    ('link_service', 'Link Service'),
    ('connect_scm', 'Connect Source Control'),
    ('connect_cicd', 'Connect CI/CD'),
    ('waiting_for_first_analysis', 'Waiting for First Analysis'),
    ('completed', 'Completed'),
]

VALID_STEPS = {code for code, _ in NEW_STEP_CHOICES}


def migrate_step_names(apps, schema_editor):
    OnboardingStatus = apps.get_model('Organisations', 'OnboardingStatus')

    for status in OnboardingStatus.objects.all():
        changed = False

        # Rewrite completed_steps: rename connect_integration, drop configure_logs.
        old_completed = list(status.completed_steps or [])
        new_completed = []
        for step in old_completed:
            if step == 'connect_integration':
                new_completed.append('connect_observability')
                changed = True
            elif step == 'configure_logs':
                # Subsumed by observability; drop.
                changed = True
                continue
            elif step in VALID_STEPS:
                new_completed.append(step)
            else:
                # Unknown step from some earlier schema — drop silently
                # rather than crash the migration on a legacy row.
                changed = True
        if changed:
            status.completed_steps = new_completed

        # Fix current_step: rename legacy names; reset unknown to welcome.
        cur = status.current_step
        if cur == 'connect_integration':
            status.current_step = 'connect_observability'
            changed = True
        elif cur == 'configure_logs':
            # No 1:1 mapping. Reset to welcome — the next GET will
            # advance the cursor based on real state.
            status.current_step = 'welcome'
            changed = True
        elif cur not in VALID_STEPS:
            status.current_step = 'welcome'
            changed = True

        if changed:
            status.save(update_fields=['completed_steps', 'current_step'])


def reverse_step_names(apps, schema_editor):
    """Best-effort reverse for a rollback.

    Renames the observability step back to connect_integration in
    completed_steps + current_step. Doesn't restore configure_logs
    (no way to know which rows had it).
    """
    OnboardingStatus = apps.get_model('Organisations', 'OnboardingStatus')

    for status in OnboardingStatus.objects.all():
        changed = False
        completed = [
            'connect_integration' if s == 'connect_observability' else s
            for s in (status.completed_steps or [])
        ]
        if completed != (status.completed_steps or []):
            status.completed_steps = completed
            changed = True
        if status.current_step == 'connect_observability':
            status.current_step = 'connect_integration'
            changed = True
        # Steps that only exist in the new schema (connect_ai_provider,
        # connect_scm, connect_cicd, waiting_for_first_analysis) can't
        # go backward cleanly — leave them and let the model complain
        # if someone tries to downgrade.
        if changed:
            status.save(update_fields=['completed_steps', 'current_step'])


class Migration(migrations.Migration):

    dependencies = [
        ('Organisations', '0009_organisations_is_demo'),
    ]

    operations = [
        migrations.AddField(
            model_name='onboardingstatus',
            name='skipped_steps',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Skippable steps the user has dismissed for now.',
            ),
        ),
        migrations.AlterField(
            model_name='onboardingstatus',
            name='current_step',
            field=models.CharField(
                choices=NEW_STEP_CHOICES,
                default='welcome',
                help_text='Cursor into the step list — the first un-resolved step.',
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name='onboardingstatus',
            name='completed_steps',
            field=models.JSONField(
                blank=True, default=list,
                help_text='Steps that pass their computed completion check.',
            ),
        ),
        migrations.AlterField(
            model_name='onboardingstatus',
            name='is_skipped',
            field=models.BooleanField(
                default=False,
                help_text='UI-only: wizard is hidden. Onboarding may still be incomplete.',
            ),
        ),
        migrations.AlterField(
            model_name='onboardingstatus',
            name='is_completed',
            field=models.BooleanField(
                default=False,
                help_text='All required steps resolved AND first analysis completed.',
            ),
        ),
        migrations.AlterField(
            model_name='onboardingstatus',
            name='onboarding_data',
            field=models.JSONField(
                blank=True, default=dict,
                help_text='Wizard scratchpad: last-picked integration_id, first_analysis_dispatched_at, etc.',
            ),
        ),
        migrations.RunPython(migrate_step_names, reverse_step_names),
    ]
