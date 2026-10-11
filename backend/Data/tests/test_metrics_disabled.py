"""Batch creation with METRICS_ENABLED off.

`METRICS_ENABLED` defaults to FALSE:

    METRICS_ENABLED = getattr(settings, 'METRICS_ENABLED',
                              os.getenv('METRICS_ENABLED', 'false').lower() == 'true')

and the disabled branch set only `serialized_metrics`, leaving `metrics`
unbound. A little further down, `preprocess_metrics_for_ai(metrics) if metrics
else {}` reads it unconditionally, so batch creation raised
UnboundLocalError and Celery retried it to exhaustion.

That was the DEFAULT path. Found on a Helm-deployed instance, where nothing
sets the variable; docker-compose installs escaped it only because
.env.example sets METRICS_ENABLED=true.
"""
from datetime import datetime, timezone as dt_timezone
from unittest.mock import MagicMock, patch

from django.test import TestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment
from integrations.schemas import LogEntry


def _log_entry():
    # Must sit inside the batch window (last `interval_minutes`), or the log
    # is filtered out before the code under test is reached.
    from django.utils import timezone as dj_tz
    return LogEntry(
        timestamp=dj_tz.now(),
        message='2026-09-27T12:00:00Z ERROR checkout PaymentGatewayTimeout',
        level='ERROR',
        service='checkout',
        labels={
            'service_name': 'checkout', 'environment': 'production',
            'project_name': 'metrics-off', 'organisation_name': 'MetricsOff Org',
            '_index': 'logs-*',
        },
        raw_id='log-1',
    )


class MetricsDisabledBatchTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='MetricsOff Org')
        self.project = Project.objects.create(
            organisation=self.org, name='metrics-off')
        self.env = ProjectEnvironment.objects.create(
            project=self.project, name='production',
            display_name='Production', log_label_value='production')

    def _run(self, metrics_enabled):
        """Drive create_log_batch_with_project_name with one log available."""
        provider = MagicMock()
        provider.search.return_value = [_log_entry()]
        provider.get_indices.return_value = ['logs-*']

        from Data import tasks
        with patch.object(tasks, 'METRICS_ENABLED', metrics_enabled), \
             patch.object(
                 tasks.IntegrationRegistry, 'get_log_provider_for_org',
                 return_value=provider), \
             patch.object(
                 tasks.IntegrationRegistry, 'get_metric_provider_for_org',
                 return_value=None):
            return tasks.create_log_batch_with_project_name(
                project_name='metrics-off', project=self.project.id,
                environment=self.env.id, interval_minutes=30,
            )

    def test_disabled_metrics_does_not_raise(self):
        """The regression: this raised UnboundLocalError, not an error the
        caller could interpret."""
        try:
            self._run(metrics_enabled=False)
        except UnboundLocalError as exc:
            self.fail(f'batch creation crashed with metrics disabled: {exc}')

    def test_disabled_metrics_returns_an_outcome_not_an_exception(self):
        """The task must complete and report an outcome. Before the fix it
        raised UnboundLocalError, which Celery retried to exhaustion — the
        operator saw repeated failures with no usable message."""
        result = self._run(metrics_enabled=False)
        self.assertIsInstance(result, str)
        self.assertNotIn('Traceback', result)

    def test_enabled_metrics_path_still_works(self):
        """Guard the branch that already worked. With no metric provider the
        fetch returns empty series, which must not crash either."""
        try:
            result = self._run(metrics_enabled=True)
        except UnboundLocalError as exc:
            self.fail(f'enabled path regressed: {exc}')
        self.assertIsInstance(result, str)


# NOTE: these tests deliberately stop at "the task completes and reports an
# outcome" rather than asserting a batch row appears. Getting a mocked log all
# the way through ES-shape conversion, dedup and the environment filter needs
# more fixture fidelity than this bug warrants, and would couple the test to
# internals unrelated to METRICS_ENABLED. Batch creation with metrics disabled
# was verified end-to-end on the validation cluster instead.


class MetricsEnabledDefaultTest(TestCase):
    """Pins the surprising default, so a future reader does not assume
    metrics are on unless something turns them off."""

    def test_default_is_false_when_unset(self):
        import importlib
        import os
        from django.test import override_settings
        with override_settings(), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('METRICS_ENABLED', None)
            from django.conf import settings
            had = hasattr(settings, 'METRICS_ENABLED')
            if had:
                self.skipTest('settings.METRICS_ENABLED overrides the env default')
            from Data import tasks
            importlib.reload(tasks)
            self.assertFalse(
                tasks.METRICS_ENABLED,
                'default changed — the Helm chart and .env both rely on '
                'setting this explicitly',
            )
