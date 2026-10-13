"""Tests for ingest health analysis.

Covers:
  * Pure analyzer semantics (canonical vs alias vs missing, precedence,
    severity thresholds, empty-sample edge case).
  * Warning + recommendation generation.
  * Collector: sample-size + window clamping.
  * API endpoint: shape, permissions, security (no credentials leak).
  * CLI command: exit codes, output shape, JSON mode.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from Organisations.models import Organisations
from integrations.field_aliases import SERVICE_NAME_ALIASES
from integrations.health import (
    CANONICAL_FIELDS,
    MAX_SAMPLE_SIZE,
    MAX_SAMPLE_WINDOW_MIN,
    FieldReport,
    IngestHealthReport,
    _clamp,
    analyze_records,
    build_recommendations,
    build_warnings,
)

User = get_user_model()


# ============================================================================
# Pure analyzer semantics
# ============================================================================


class AnalyzeRecordsTest(SimpleTestCase):
    """`analyze_records` counts canonical vs alias vs missing correctly."""

    def _svc_report(self, records):
        return analyze_records(records, {'service_name': SERVICE_NAME_ALIASES})[0]

    def test_all_canonical_present(self):
        r = self._svc_report([{'service_name': 'a'}] * 10)
        self.assertEqual(r.canonical_count, 10)
        self.assertEqual(r.missing_count, 0)
        self.assertEqual(r.alias_counts, {})
        self.assertEqual(r.canonical_pct, 100.0)
        self.assertEqual(r.severity, 'ok')

    def test_alias_only_dominates(self):
        r = self._svc_report([{'service': 'a'}] * 10)  # Datadog USM
        self.assertEqual(r.canonical_count, 0)
        self.assertEqual(r.alias_counts, {'service': 10})
        self.assertEqual(r.severity, 'info')
        self.assertIn('service', r.message)

    def test_all_missing_is_warning(self):
        r = self._svc_report([{'unrelated_field': 'x'}] * 10)
        self.assertEqual(r.missing_count, 10)
        self.assertEqual(r.severity, 'warning')

    def test_canonical_wins_when_both_present(self):
        """If both canonical AND an alias appear on the same record,
        canonical is counted (never double-count)."""
        r = self._svc_report([{'service_name': 'x', 'service': 'y'}])
        self.assertEqual(r.canonical_count, 1)
        self.assertEqual(r.alias_counts, {})

    def test_first_matching_alias_used(self):
        """Aliases are checked in list order — highest-precedence alias
        wins if canonical is missing."""
        # SERVICE_NAME_ALIASES order: service_name, service, service.name, app, app.kubernetes.io/name
        r = self._svc_report([{'app': 'a', 'service': 'b'}])
        # `service` comes before `app` in the alias list.
        self.assertEqual(r.alias_counts, {'service': 1})

    def test_empty_string_treated_as_missing(self):
        # A present-but-empty canonical must not shadow a real alias.
        r = self._svc_report([{'service_name': '', 'service': 'a'}])
        self.assertEqual(r.canonical_count, 0)
        self.assertEqual(r.alias_counts, {'service': 1})

    def test_empty_sample_no_crash(self):
        r = self._svc_report([])
        self.assertEqual(r.total, 0)
        self.assertEqual(r.canonical_pct, 0.0)
        self.assertEqual(r.coverage_pct, 0.0)
        # severity may be 'warning' or 'ok' depending on impl — either
        # is acceptable for empty samples, but message should be safe.
        self.assertIn(r.canonical, r.message)


class SeverityThresholdsTest(SimpleTestCase):
    """FieldReport.severity is derived correctly at boundaries."""

    def _report(self, canonical, alias, missing, total):
        return FieldReport(
            canonical='service_name',
            canonical_count=canonical,
            alias_counts={'service': alias} if alias else {},
            missing_count=missing,
            total=total,
        )

    def test_80pct_canonical_is_ok(self):
        self.assertEqual(self._report(80, 0, 20, 100).severity, 'ok')

    def test_79pct_canonical_is_not_ok(self):
        self.assertNotEqual(self._report(79, 0, 21, 100).severity, 'ok')

    def test_alias_coverage_gives_info(self):
        # canonical 0%, alias 95% -> info
        self.assertEqual(self._report(0, 95, 5, 100).severity, 'info')

    def test_low_coverage_is_warning(self):
        # canonical 0%, alias 20% -> warning
        self.assertEqual(self._report(0, 20, 80, 100).severity, 'warning')


class WarningsAndRecommendationsTest(SimpleTestCase):
    def test_warning_generated_for_missing_field(self):
        f = FieldReport('service_name', 0, {}, 100, 100)  # all missing
        warnings = build_warnings([f])
        self.assertEqual(len(warnings), 1)
        self.assertIn('service_name', warnings[0])
        self.assertIn('100/100', warnings[0])

    def test_no_warning_when_covered_by_aliases(self):
        f = FieldReport('service_name', 0, {'service': 95}, 5, 100)  # info
        self.assertEqual(build_warnings([f]), [])

    def test_recommendation_when_alias_dominant(self):
        f = FieldReport('service_name', 0, {'service': 95}, 5, 100)
        recs = build_recommendations([f])
        self.assertEqual(len(recs), 1)
        # Recommendation identifies both the canonical target and the alias in use.
        self.assertIn('service_name', recs[0])
        self.assertIn('service', recs[0])


# ============================================================================
# Collector — clamps + graceful error handling
# ============================================================================


class ClampTest(SimpleTestCase):
    def test_clamp_within_range(self):
        self.assertEqual(_clamp(500, 10, 1000), 500)

    def test_clamp_low(self):
        self.assertEqual(_clamp(5, 10, 1000), 10)

    def test_clamp_high(self):
        self.assertEqual(_clamp(9999, 10, 1000), 1000)

    def test_max_bounds(self):
        self.assertEqual(MAX_SAMPLE_SIZE, 1000)
        self.assertEqual(MAX_SAMPLE_WINDOW_MIN, 1440)


class CollectIngestHealthErrorHandlingTest(SimpleTestCase):
    """Sampling failures produce a report with `.error` set, not an exception."""

    @patch('integrations.health._sample_records', side_effect=RuntimeError('adapter down'))
    def test_adapter_exception_returns_report_with_error(self, _mock):
        from integrations.health import collect_ingest_health
        integration = MagicMock()
        integration.id = 42
        integration.display_name = 'test'
        integration.provider = 'elasticsearch'
        integration.capabilities = ['logs']

        report = collect_ingest_health(integration, sample_size=50, sample_window_minutes=30)
        self.assertIsNotNone(report.error)
        self.assertIn('adapter down', report.error)
        # Fields empty because we never got past the sample step.
        self.assertEqual(report.fields, [])


# ============================================================================
# API endpoint — permissions + no-credentials guarantee
# ============================================================================


class IngestHealthEndpointTest(TestCase):
    """The `/ingest-health/` action does the right auth + doesn't leak creds."""

    def setUp(self):
        from integrations.models import ObservabilityIntegration
        self.org = Organisations.objects.create(name='HealthEndpointOrg')
        self.other_org = Organisations.objects.create(name='OtherOrg')

        self.member = User.objects.create_user(
            username='member', email='member@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.outsider = User.objects.create_user(
            username='outsider', email='outsider@t.com', password='p',
            organisation=self.other_org, role='admin', is_active=True,
        )

        self.integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='org-es',
            capabilities=['logs'],
            host='https://es.internal:9200',
        )
        # Store a real password so the demo short-circuit doesn't fire.
        self.integration.set_password('super-secret-do-not-leak')
        self.integration.save()

        self.client = APIClient()
        self.url = f'/api/integrations/observability/{self.integration.id}/ingest-health/'

    def test_unauthenticated_401_or_403(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_outsider_from_other_org_cannot_view(self):
        """Get-object is queryset-scoped by org — outsider gets 404."""
        self.client.force_authenticate(user=self.outsider)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    @patch('integrations.health._sample_records', return_value=[
        {'service_name': 'checkout', 'environment': 'prod'},
        {'service': 'api', 'env': 'staging'},
        {'unrelated': 'x'},
    ])
    def test_member_can_view_and_shape_is_correct(self, _mock):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['integration_id'], self.integration.id)
        self.assertEqual(data['provider'], 'elasticsearch')
        self.assertEqual(data['provider_type'], 'logs')
        self.assertIsInstance(data['fields'], list)
        self.assertGreater(len(data['fields']), 0)
        # Every field record has the canonical + aliases + severity fields.
        for f in data['fields']:
            self.assertIn('canonical', f)
            self.assertIn('canonical_count', f)
            self.assertIn('alias_counts', f)
            self.assertIn('severity', f)

    @patch('integrations.health._sample_records', return_value=[
        {'service_name': 'checkout'},
    ])
    def test_ingest_health_never_leaks_credentials(self, _mock):
        """Regression guard: response JSON must not contain the password/host.

        This is the security-critical assertion — if a future refactor
        accidentally serialises `integration.config` or `integration.get_password()`
        into the response, this test catches it.
        """
        self.client.force_authenticate(user=self.member)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        raw = response.content.decode()
        self.assertNotIn('super-secret-do-not-leak', raw)
        # Host is metadata a curious admin might argue is fine, but keep the
        # boundary tight: the report should NEVER include config values.
        self.assertNotIn('es.internal:9200', raw)

    def test_bad_query_params_400(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(self.url + '?minutes=abc')
        self.assertEqual(response.status_code, 400)

    @patch('integrations.health._sample_records', return_value=[])
    def test_zero_records_returns_ok(self, _mock):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(self.url + '?minutes=1&limit=10')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['sample_size'], 0)


# ============================================================================
# CLI command — exit codes + JSON mode
# ============================================================================


class CheckIngestCommandTest(TestCase):
    def setUp(self):
        from integrations.models import ObservabilityIntegration
        self.org = Organisations.objects.create(name='CmdOrg')
        self.integration = ObservabilityIntegration.objects.create(
            organisation=self.org,
            provider='elasticsearch',
            display_name='cmd-es',
            capabilities=['logs'],
            host='https://es:9200',
        )
        self.integration.set_password('sekret')
        self.integration.save()

    def test_missing_integration_raises(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('check_ingest', '--integration=999999')

    @patch('integrations.health._sample_records', return_value=[
        {'service_name': 'checkout'},
    ])
    def test_json_mode_valid_json(self, _mock):
        import io
        import json as _json
        out = io.StringIO()
        call_command('check_ingest', '--integration', str(self.integration.id),
                     '--json', stdout=out)
        parsed = _json.loads(out.getvalue())
        self.assertEqual(parsed['integration_id'], self.integration.id)
        self.assertIn('fields', parsed)

    @patch('integrations.health._sample_records', return_value=[
        {'service_name': 'checkout'},
    ])
    def test_text_mode_contains_headers(self, _mock):
        import io
        out = io.StringIO()
        call_command('check_ingest', '--integration', str(self.integration.id),
                     stdout=out)
        text = out.getvalue()
        self.assertIn('SerOps Ingest Health', text)
        self.assertIn('Canonical field presence', text)
