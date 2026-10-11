"""Tests for the reworked onboarding wizard (item #11, 2026-08-30).

Covers:
- ``OnboardingStatus`` model computed-state semantics
- ``OnboardingStatusView`` (GET / PUT skip_step / PUT store_data)
- ``OnboardingSkipView`` — dismiss doesn't complete
- ``OnboardingResumeView`` — un-dismiss
- ``OnboardingResetView`` (admin-only)
- ``dispatch_first_analysis_on_service_link`` signal handler
- Data migration (legacy step-name rewriting)
"""

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations, OnboardingStatus
from Users.models import User


# ---------------------------------------------------------------------------
# View tests
# ---------------------------------------------------------------------------


class TestOnboardingStatusView(APITestCase):
    """Tests for GET /api/organisation/onboarding/status/"""

    def setUp(self):
        self.org = Organisations.objects.create(name='Onboard Org', website='https://ob.com')
        self.admin = User.objects.create_user(
            username='obadmin', email='ob@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('onboarding-status')

    def test_get_returns_computed_state_and_progress(self):
        """GET returns the full serializer payload including computed_state."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ('current_step', 'completed_steps', 'skipped_steps',
                    'computed_state', 'progress_percentage', 'is_completed',
                    'is_skipped', 'onboarding_data', 'available_steps'):
            self.assertIn(key, response.data, f"missing '{key}' in response")
        # New org: no real state exists, so cursor sits on the first
        # required step and computed state is all-False (except welcome).
        self.assertEqual(response.data['current_step'], 'connect_ai_provider')
        self.assertEqual(response.data['progress_percentage'], 0)
        self.assertFalse(response.data['is_completed'])
        self.assertEqual(response.data['computed_state']['welcome'], True)
        self.assertEqual(response.data['computed_state']['connect_ai_provider'], False)

    def test_get_creates_if_missing(self):
        """GET auto-creates OnboardingStatus via get_or_create_for_org."""
        self.assertFalse(OnboardingStatus.objects.filter(organisation=self.org).exists())
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(OnboardingStatus.objects.filter(organisation=self.org).exists())

    def test_available_steps_include_skippable_flag(self):
        """The available_steps payload advertises which steps are skippable."""
        response = self.client.get(self.url)
        steps = {s['code']: s['skippable'] for s in response.data['available_steps']}
        self.assertTrue(steps['connect_scm'])
        self.assertTrue(steps['connect_cicd'])
        self.assertFalse(steps['connect_ai_provider'])
        self.assertFalse(steps['connect_observability'])

    def test_put_skip_step_accepts_skippable(self):
        """PUT action=skip_step marks an optional step as user-skipped."""
        response = self.client.put(
            self.url,
            {'action': 'skip_step', 'step': 'connect_scm'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('connect_scm', response.data['skipped_steps'])

    def test_put_skip_step_rejects_required(self):
        """PUT action=skip_step on a required step returns 400."""
        response = self.client.put(
            self.url,
            {'action': 'skip_step', 'step': 'connect_ai_provider'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cannot be skipped', response.data['error'].lower())

    def test_put_skip_step_missing_step_returns_400(self):
        response = self.client.put(self.url, {'action': 'skip_step'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_store_data_merges_into_onboarding_data(self):
        """PUT action=store_data merges the payload into onboarding_data."""
        response = self.client.put(
            self.url,
            {'action': 'store_data', 'data': {'selected_provider': 'gemini'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        onboarding = OnboardingStatus.objects.get(organisation=self.org)
        self.assertEqual(onboarding.onboarding_data.get('selected_provider'), 'gemini')

    def test_put_store_data_rejects_non_object_payload(self):
        response = self.client.put(
            self.url,
            {'action': 'store_data', 'data': 'not-a-dict'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_put_unknown_action_returns_400(self):
        response = self.client.put(self.url, {'action': 'do_a_flip'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestOnboardingSkipView(APITestCase):
    """POST /api/organisation/onboarding/skip/ — dismiss the wizard UI only."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Skip Org', website='https://skip.com')
        self.admin = User.objects.create_user(
            username='skipadmin', email='skip@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('onboarding-skip')

    def test_dismiss_sets_is_skipped_but_not_is_completed(self):
        """Regression guard: prior semantics also set is_completed=True
        which lied about activation. New behaviour is UI-only."""
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_skipped'])
        self.assertFalse(response.data['is_completed'])

        onboarding = OnboardingStatus.objects.get(organisation=self.org)
        self.assertTrue(onboarding.is_skipped)
        self.assertIsNotNone(onboarding.skipped_at)
        self.assertFalse(onboarding.is_completed)
        # Old code set current_step='completed'; new code leaves the cursor alone.
        self.assertNotEqual(onboarding.current_step, 'completed')

    def test_dismiss_is_idempotent(self):
        OnboardingStatus.objects.create(organisation=self.org, is_skipped=True)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_skipped'])

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class TestOnboardingResumeView(APITestCase):
    """POST /api/organisation/onboarding/resume/ — un-dismiss the wizard."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Resume Org', website='https://r.com')
        self.admin = User.objects.create_user(
            username='resumeadmin', email='res@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('onboarding-resume')

    def test_resume_clears_is_skipped(self):
        OnboardingStatus.objects.create(
            organisation=self.org, is_skipped=True,
        )
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_skipped'])
        onboarding = OnboardingStatus.objects.get(organisation=self.org)
        self.assertFalse(onboarding.is_skipped)
        self.assertIsNone(onboarding.skipped_at)


class TestOnboardingResetView(APITestCase):
    """POST /api/organisation/onboarding/reset/ (admin-only)"""

    def setUp(self):
        self.org = Organisations.objects.create(name='Reset Org', website='https://reset.com')
        self.admin = User.objects.create_user(
            username='resetadmin', email='reset@test.com',
            password='Test123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.viewer = User.objects.create_user(
            username='resetviewer', email='rv@test.com',
            password='Test123!', organisation=self.org,
            role='viewer', is_active=True,
        )
        self.regular_user = User.objects.create_user(
            username='resetuser', email='ru@test.com',
            password='Test123!', organisation=self.org,
            role='user', is_active=True,
        )
        self.url = reverse('onboarding-reset')

    def test_reset_onboarding_admin(self):
        """POST as admin clears completed_steps, skipped_steps, flags."""
        onboarding = OnboardingStatus.objects.create(
            organisation=self.org,
            current_step='connect_observability',
            completed_steps=['connect_ai_provider'],
            skipped_steps=['connect_scm'],
            is_skipped=False,
            onboarding_data={'selected_provider': 'gemini'},
        )
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        onboarding.refresh_from_db()
        self.assertEqual(onboarding.current_step, 'welcome')
        self.assertEqual(onboarding.completed_steps, [])
        self.assertEqual(onboarding.skipped_steps, [])
        self.assertFalse(onboarding.is_skipped)
        self.assertFalse(onboarding.is_completed)
        self.assertEqual(onboarding.onboarding_data, {})

    def test_reset_denied_for_viewer(self):
        OnboardingStatus.objects.create(organisation=self.org)
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reset_denied_for_user(self):
        OnboardingStatus.objects.create(organisation=self.org)
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestOnboardingStatusModel(TestCase):
    """Unit tests for OnboardingStatus model methods (no HTTP layer)."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Model Org', website='https://model.com')
        self.onboarding = OnboardingStatus.objects.create(organisation=self.org)

    def test_progress_percentage_empty(self):
        self.assertEqual(self.onboarding.progress_percentage, 0)

    def test_progress_percentage_counts_completed_and_skipped(self):
        """Completed + skipped both count toward resolved-steps %."""
        # 2 completed + 1 skipped, out of 7 tracked steps
        self.onboarding.completed_steps = ['connect_ai_provider', 'connect_observability']
        self.onboarding.skipped_steps = ['connect_scm']
        self.onboarding.save()
        # 3/7 = 42%
        self.assertEqual(self.onboarding.progress_percentage, 42)

    def test_progress_percentage_ignores_stale_step_names(self):
        """Rows migrated from the old schema might have leftover cruft
        in completed_steps — we count only tracked steps."""
        self.onboarding.completed_steps = [
            'connect_ai_provider', 'legacy_step_that_no_longer_exists',
        ]
        self.onboarding.save()
        # Only connect_ai_provider counts → 1/7 = 14%
        self.assertEqual(self.onboarding.progress_percentage, 14)

    def test_skip_step_rejects_required_step(self):
        with self.assertRaises(ValueError) as ctx:
            self.onboarding.skip_step('connect_ai_provider')
        self.assertIn('cannot be skipped', str(ctx.exception).lower())

    def test_skip_step_accepts_optional_step(self):
        self.onboarding.skip_step('connect_scm')
        self.assertIn('connect_scm', self.onboarding.skipped_steps)

    def test_skip_step_is_idempotent(self):
        self.onboarding.skip_step('connect_scm')
        self.onboarding.skip_step('connect_scm')
        # Only recorded once
        self.assertEqual(self.onboarding.skipped_steps.count('connect_scm'), 1)

    def test_store_data_merges(self):
        self.onboarding.store_data({'a': 1})
        self.onboarding.store_data({'b': 2})
        self.assertEqual(self.onboarding.onboarding_data, {'a': 1, 'b': 2})

    def test_dismiss_sets_flag_but_not_complete(self):
        self.onboarding.dismiss()
        self.assertTrue(self.onboarding.is_skipped)
        self.assertIsNotNone(self.onboarding.skipped_at)
        self.assertFalse(self.onboarding.is_completed)

    def test_resume_clears_flag(self):
        self.onboarding.dismiss()
        self.onboarding.resume()
        self.assertFalse(self.onboarding.is_skipped)
        self.assertIsNone(self.onboarding.skipped_at)

    def test_reset_clears_all_including_skipped_steps(self):
        self.onboarding.skipped_steps = ['connect_scm']
        self.onboarding.is_completed = True
        self.onboarding.onboarding_data = {'foo': 'bar'}
        self.onboarding.save()
        self.onboarding.reset()
        self.assertEqual(self.onboarding.current_step, 'welcome')
        self.assertEqual(self.onboarding.completed_steps, [])
        self.assertEqual(self.onboarding.skipped_steps, [])
        self.assertFalse(self.onboarding.is_completed)
        self.assertEqual(self.onboarding.onboarding_data, {})

    def test_deprecated_mark_step_complete_is_no_op_for_completion(self):
        """The old ``mark_step_complete`` API no longer decides completion.
        It only stores scratchpad data now. Actual completion comes from
        real DB state."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', DeprecationWarning)
            self.onboarding.mark_step_complete(
                'connect_ai_provider', {'stored': 'here'},
            )
        # completed_steps was NOT populated by the fake "attestation" —
        # it comes from computed state, which is still all-False.
        self.assertNotIn('connect_ai_provider', self.onboarding.completed_steps)
        # But the data payload did get stored (that was the legitimate
        # side-effect of the old call).
        self.assertEqual(self.onboarding.onboarding_data.get('stored'), 'here')


# ---------------------------------------------------------------------------
# Computed state — integration with real data
# ---------------------------------------------------------------------------


class TestComputedState(TestCase):
    """Verify each step's completion detector reads real DB state."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Compute Org', website='https://c.com')
        self.onboarding = OnboardingStatus.objects.create(organisation=self.org)

    def test_all_false_on_fresh_org(self):
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['welcome'])
        for step in ('connect_ai_provider', 'connect_observability',
                     'create_project', 'link_service',
                     'connect_scm', 'connect_cicd',
                     'waiting_for_first_analysis'):
            self.assertFalse(state[step], f'{step} should be False on fresh org')

    def test_ai_provider_detected_from_active_org_api_key(self):
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        gemini = AIModelProvider.objects.get(name='gemini')
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=gemini,
            api_key='encrypted-blob', is_active=True,
        )
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['connect_ai_provider'])

    def test_ai_provider_detected_for_keyless_ollama(self):
        """Ollama is keyless — its 'configured' signal is having it
        set as the org's default_provider, not an OrganisationAPIKey row."""
        from org_settings.models import AIModelProvider, OrganisationAISettings
        ollama = AIModelProvider.objects.get(name='ollama')
        OrganisationAISettings.objects.create(
            organisation=self.org, default_provider=ollama,
        )
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['connect_ai_provider'])

    def test_observability_requires_logs_capability(self):
        """A metrics-only integration doesn't count — SerOps is log-centric."""
        from integrations.models import ObservabilityIntegration
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='prometheus',
            display_name='Metrics only', is_active=True,
            capabilities=['metrics'],
        )
        state = self.onboarding.get_computed_state()
        self.assertFalse(state['connect_observability'])

        # Add a logs-capable one — flips.
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki',
            display_name='Logs', is_active=True,
            capabilities=['logs'],
        )
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['connect_observability'])

    def test_project_and_service_detection(self):
        from Projects.models import Project, ProjectService
        project = Project.objects.create(name='P', organisation=self.org)
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['create_project'])
        self.assertFalse(state['link_service'])

        ProjectService.objects.create(name='svc', project=project)
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['link_service'])

    def test_waiting_for_first_analysis_flips_when_batch_analyzed(self):
        from Data.models import AIAnalyzedBatch
        from django.utils import timezone

        # Batch without analyzed_at → not counted (it exists but never ran)
        AIAnalyzedBatch.objects.create(
            batch_id='b1', organisation=self.org,
        )
        state = self.onboarding.get_computed_state()
        self.assertFalse(state['waiting_for_first_analysis'])

        # Set analyzed_at → flips
        b2 = AIAnalyzedBatch.objects.create(
            batch_id='b2', organisation=self.org,
            analyzed_at=timezone.now(),
        )
        state = self.onboarding.get_computed_state()
        self.assertTrue(state['waiting_for_first_analysis'])


class TestRefreshAndAdvance(TestCase):
    """Verify refresh_and_advance parks the cursor correctly + sets is_completed."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Advance Org', website='https://a.com')
        self.onboarding = OnboardingStatus.objects.create(organisation=self.org)

    def test_cursor_lands_on_first_unresolved_step(self):
        # Fresh org — first un-resolved is connect_ai_provider (welcome is auto-true)
        self.onboarding.refresh_and_advance()
        self.assertEqual(self.onboarding.current_step, 'connect_ai_provider')

    def test_cursor_skips_completed_steps(self):
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        gemini = AIModelProvider.objects.get(name='gemini')
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=gemini,
            api_key='blob', is_active=True,
        )
        self.onboarding.refresh_and_advance()
        # AI provider done → cursor advances to observability
        self.assertEqual(self.onboarding.current_step, 'connect_observability')
        self.assertIn('connect_ai_provider', self.onboarding.completed_steps)

    def test_cursor_skips_user_dismissed_optional_step(self):
        """User dismissed SCM → cursor jumps to next un-resolved."""
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        from integrations.models import ObservabilityIntegration
        from Projects.models import Project, ProjectService

        # Complete all required-before-SCM
        gemini = AIModelProvider.objects.get(name='gemini')
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=gemini,
            api_key='blob', is_active=True,
        )
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki', display_name='L',
            is_active=True, capabilities=['logs'],
        )
        project = Project.objects.create(name='P', organisation=self.org)
        ProjectService.objects.create(name='svc', project=project)

        self.onboarding.skip_step('connect_scm')
        self.onboarding.skip_step('connect_cicd')
        self.onboarding.refresh_and_advance()
        # All resolved except waiting_for_first_analysis (no batch yet).
        self.assertEqual(self.onboarding.current_step, 'waiting_for_first_analysis')
        self.assertFalse(self.onboarding.is_completed)

    def test_is_completed_requires_first_analysis(self):
        """Skipping optionals + finishing everything else is NOT enough
        for is_completed — first analysis is the aha-moment gate."""
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        from integrations.models import ObservabilityIntegration
        from Projects.models import Project, ProjectService

        gemini = AIModelProvider.objects.get(name='gemini')
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=gemini, api_key='blob', is_active=True,
        )
        ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki', display_name='L',
            is_active=True, capabilities=['logs'],
        )
        project = Project.objects.create(name='P', organisation=self.org)
        ProjectService.objects.create(name='svc', project=project)
        self.onboarding.skip_step('connect_scm')
        self.onboarding.skip_step('connect_cicd')
        self.onboarding.refresh_and_advance()
        self.assertFalse(self.onboarding.is_completed)

        # First analysis lands → is_completed flips.
        from Data.models import AIAnalyzedBatch
        from django.utils import timezone
        AIAnalyzedBatch.objects.create(
            batch_id='b', organisation=self.org, analyzed_at=timezone.now(),
        )
        self.onboarding.refresh_and_advance()
        self.assertTrue(self.onboarding.is_completed)
        self.assertEqual(self.onboarding.current_step, 'completed')

    def test_is_completed_regresses_if_required_state_disappears(self):
        """If admin deletes the observability integration, wizard un-completes.
        That's honest behaviour — reporting 'activated' for an org that
        no longer has the required infra would be a lie."""
        from org_settings.models import AIModelProvider, OrganisationAPIKey
        from integrations.models import ObservabilityIntegration
        from Projects.models import Project, ProjectService
        from Data.models import AIAnalyzedBatch
        from django.utils import timezone

        gemini = AIModelProvider.objects.get(name='gemini')
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=gemini, api_key='blob', is_active=True,
        )
        obs = ObservabilityIntegration.objects.create(
            organisation=self.org, provider='loki', display_name='L',
            is_active=True, capabilities=['logs'],
        )
        project = Project.objects.create(name='P', organisation=self.org)
        ProjectService.objects.create(name='svc', project=project)
        AIAnalyzedBatch.objects.create(
            batch_id='b', organisation=self.org, analyzed_at=timezone.now(),
        )
        self.onboarding.refresh_and_advance()
        self.assertTrue(self.onboarding.is_completed)

        # Blow up the observability integration.
        obs.delete()
        self.onboarding.refresh_and_advance()
        self.assertFalse(self.onboarding.is_completed)
        self.assertIsNone(self.onboarding.completed_at)


# ---------------------------------------------------------------------------
# Signal: dispatch first analysis when a ProjectService is created
# ---------------------------------------------------------------------------


class TestFirstAnalysisDispatchSignal(TestCase):
    """The post_save on ProjectService should trigger an immediate batch
    when the org is still in onboarding — this is what drops TTV from
    ~10 min (Celery beat) to seconds. Guarded so it only fires once."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Signal Org', website='https://s.com')
        from Projects.models import Project
        self.project = Project.objects.create(name='SigProj', organisation=self.org)

    @patch('Data.tasks.create_log_batch_with_project_name.delay')
    def test_signal_fires_on_first_service_create(self, mock_delay):
        from Projects.models import ProjectService
        ProjectService.objects.create(name='svc', project=self.project)
        mock_delay.assert_called_once()

        # Idempotency marker written
        onboarding = OnboardingStatus.objects.get(organisation=self.org)
        self.assertIn('first_analysis_dispatched_at', onboarding.onboarding_data)

    @patch('Data.tasks.create_log_batch_with_project_name.delay')
    def test_signal_does_not_fire_twice(self, mock_delay):
        """Creating a second service before the first analysis returns
        must not queue a duplicate batch task."""
        from Projects.models import ProjectService
        ProjectService.objects.create(name='svc1', project=self.project)
        ProjectService.objects.create(name='svc2', project=self.project)
        self.assertEqual(mock_delay.call_count, 1)

    @patch('Data.tasks.create_log_batch_with_project_name.delay')
    def test_signal_does_not_fire_on_update(self, mock_delay):
        """Post-create edits to a service must not re-dispatch."""
        from Projects.models import ProjectService
        svc = ProjectService.objects.create(name='svc', project=self.project)
        mock_delay.reset_mock()
        svc.name = 'renamed'
        svc.save()
        mock_delay.assert_not_called()

    @patch('Data.tasks.create_log_batch_with_project_name.delay')
    def test_signal_does_not_fire_when_onboarding_complete(self, mock_delay):
        """After onboarding, batches are scheduled by the normal beat —
        the signal must not double-dispatch."""
        OnboardingStatus.objects.create(
            organisation=self.org, is_completed=True,
        )
        from Projects.models import ProjectService
        ProjectService.objects.create(name='svc', project=self.project)
        mock_delay.assert_not_called()


# ---------------------------------------------------------------------------
# Data migration — legacy step-name rewriting
# ---------------------------------------------------------------------------


class TestMigrationStepRename(TestCase):
    """The 0010_onboarding_rework migration rewrote legacy step names.

    We can't actually re-run that migration here (Django already applied
    it), but we can verify the invariants it established: no row can
    have connect_integration or configure_logs anywhere, and any
    current_step is a valid new-schema choice.
    """

    def test_no_legacy_step_names_in_current_step_choices(self):
        """The choices tuple should no longer include the legacy names."""
        choices = {code for code, _ in OnboardingStatus.ONBOARDING_STEPS}
        self.assertNotIn('connect_integration', choices)
        self.assertNotIn('configure_logs', choices)
        # New names present
        self.assertIn('connect_ai_provider', choices)
        self.assertIn('connect_observability', choices)
        self.assertIn('connect_scm', choices)
        self.assertIn('connect_cicd', choices)
        self.assertIn('waiting_for_first_analysis', choices)
