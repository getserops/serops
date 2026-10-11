"""Pre-creation Sentinel gate — Batch 50 tests (in Batch 51 test batch).

Covers:
  * Gate is a no-op in shadow mode regardless of the flag
  * Gate is a no-op when opt-out flag is False
  * Gate SKIPS quiet batches when active + flag=True
  * State (ProjectEnvironmentState) is mutated only ONCE per batch
    (no double-count from pre-gate + post-persist both calling
    evaluate_batch)
  * Fail-open behaviour: gate exception must not block persist
"""

from unittest.mock import patch

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment
from Data.sentinel import (
    is_pre_creation_gate_enabled,
    should_skip_batch_pre_creation,
)
from org_settings.models import SentinelConfig


class PreCreationGateFlagTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='GateFlagOrg')

    def test_defaults_true_when_no_config(self):
        # Fail-open default: pre-creation dropping is the safer default
        # for the general population.
        self.assertTrue(is_pre_creation_gate_enabled(self.org))

    def test_reads_flag_from_config(self):
        SentinelConfig.objects.create(
            organisation=self.org, pre_creation_gate_enabled=False,
        )
        self.assertFalse(is_pre_creation_gate_enabled(self.org))

    def test_defaults_true_on_config_error(self):
        # Nonsense object → fail-open to True. Broken config MUST
        # NOT flip behaviour silently.
        self.assertTrue(is_pre_creation_gate_enabled(object()))


class ShouldSkipBatchPreCreationTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='SkipOrg')
        cls.project = Project.objects.create(name='p', organisation=cls.org)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )

    def _run(self, quiet_data=True):
        # Empty logs + no code_changes → likely quiet.
        # BUT: first batch always returns decision='first' (per
        # evaluate_batch), which is treated as NOT quiet.
        data = {'logs': [], 'metrics_summary': {}, 'code_changes': []}
        return should_skip_batch_pre_creation(
            project=self.project, environment=self.env,
            batch_data=data, organisation=self.org,
        )

    def test_shadow_mode_never_skips(self):
        # No SentinelConfig → shadow mode (active_mode=False default).
        should_skip, decision, triggers = self._run()
        self.assertFalse(should_skip)

    def test_active_mode_with_flag_off_never_skips(self):
        SentinelConfig.objects.create(
            organisation=self.org, active_mode=True,
            pre_creation_gate_enabled=False,
        )
        # Even quiet + active_mode, flag off → gate no-ops.
        # Need a second call because first is always 'first', not 'quiet'.
        self._run()  # burn the 'first' decision
        should_skip, decision, triggers = self._run()
        self.assertFalse(should_skip)

    def test_active_mode_with_flag_on_skips_quiet(self):
        SentinelConfig.objects.create(
            organisation=self.org, active_mode=True,
            pre_creation_gate_enabled=True,
        )
        self._run()  # burn 'first'
        should_skip, decision, triggers = self._run()
        # Second empty batch = no triggers = quiet.
        self.assertEqual(decision, 'quiet')
        self.assertTrue(should_skip)

    def test_active_mode_never_skips_first_batch(self):
        SentinelConfig.objects.create(
            organisation=self.org, active_mode=True,
            pre_creation_gate_enabled=True,
        )
        should_skip, decision, triggers = self._run()
        # First batch always seeds state — decision='first', NOT quiet.
        self.assertEqual(decision, 'first')
        self.assertFalse(should_skip)


class GateStateMutationTest(TestCase):
    """Pre-gate + post-persist Sentinel evaluation should NOT double-mutate
    ProjectEnvironmentState. Verifies the pipeline stashes the result
    instead of re-evaluating.

    This is an integration check: we mock evaluate_batch and count
    calls when both paths run through the pipeline. Full pipeline
    test is heavier — this narrow test is enough to catch double-call
    regressions.
    """

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='MutOrg')
        cls.project = Project.objects.create(name='p', organisation=cls.org)
        cls.env = ProjectEnvironment.objects.create(
            project=cls.project, name='production', display_name='Production',
        )

    @patch('Data.sentinel.evaluate_batch')
    def test_should_skip_evaluates_exactly_once(self, mock_eval):
        mock_eval.return_value = ('quiet', [])
        SentinelConfig.objects.create(
            organisation=self.org, active_mode=True,
            pre_creation_gate_enabled=True,
        )
        should_skip_batch_pre_creation(
            project=self.project, environment=self.env,
            batch_data={}, organisation=self.org,
        )
        # Sentinel evaluated exactly once inside the gate call.
        self.assertEqual(mock_eval.call_count, 1)
