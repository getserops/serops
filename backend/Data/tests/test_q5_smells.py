"""Tests for the Q5 "accumulated smells" batch (PR-Q5A).

Four smells fixed in one PR; four test classes cover them.

  #1 alert-time-scoped window: analyze_alert_ondemand → tight ±3 min
     window around ``event.received_at`` (was: full 15-min scheduler
     back-look, drowned a 30-sec incident in noise).
  #2 ambiguous project-by-service match: env-aware precedence + a
     WARNING log when the match is ambiguous (was: first-match-wins
     silently, mis-routed alerts to whichever project sorted first).
  #3 slow_span_after_deploy directory heuristic: owner-declared
     service→path globs override the fragile ``/{svc}/`` heuristic
     (was: monorepo + package-style repo layouts silently missed
     the match).
  #4 timeline pagination: build_unified_timeline gains an ``offset``,
     the view returns pre-slice ``total_events`` + ``has_more`` (was:
     silently capped at 200 with no way for the client to know it
     was truncated).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from Data.correlation_engine import correlate_spans_with_code_changes
from Data.models import AIAnalyzedBatch, AlertEvent
from Data.unified_timeline import build_unified_timeline_with_total
from Organisations.models import Organisations
from Projects.models import Project, ProjectEnvironment, ProjectService
from Users.models import User


# ---------------------------------------------------------------------------
# Q5-1 + Q5-2 — alert-triggered helpers
# ---------------------------------------------------------------------------


class AlertWindowTest(TestCase):
    """The alert helper computes a ±3 min window around received_at,
    both boundaries serialised as ISO-8601 strings so Celery can carry
    them across the broker."""

    def setUp(self):
        self.org = Organisations.objects.create(name='AlertWinOrg')

    def _event(self, received_at=None):
        e = AlertEvent.objects.create(
            organisation=self.org,
            source='alertmanager',
            alertname='HighErrorRate',
            state='firing',
        )
        if received_at is not None:
            # auto_now_add can't be overridden through create(); do a
            # direct-attribute rewrite for deterministic anchoring.
            AlertEvent.objects.filter(pk=e.pk).update(received_at=received_at)
            e.refresh_from_db()
        return e

    def test_window_is_iso_strings_and_six_minutes_wide(self):
        from Data.tasks import _alert_window
        anchor = timezone.now().replace(microsecond=0)
        event = self._event(received_at=anchor)
        start_iso, end_iso = _alert_window(event)
        self.assertIsInstance(start_iso, str)
        self.assertIsInstance(end_iso, str)

        from datetime import datetime
        start = datetime.fromisoformat(start_iso)
        end = datetime.fromisoformat(end_iso)
        self.assertEqual(end - start, timedelta(minutes=6))
        # Anchor sits at the midpoint.
        self.assertEqual((anchor - start), timedelta(minutes=3))

    def test_missing_received_at_falls_back_to_now(self):
        """Defensive path: a corrupt AlertEvent with no received_at
        still produces a valid window instead of crashing."""
        from Data.tasks import _alert_window
        event = self._event()
        event.received_at = None   # in-memory only; DB row is unchanged.
        start_iso, end_iso = _alert_window(event)
        # Both parseable and 6 min apart.
        from datetime import datetime
        span = datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)
        self.assertEqual(span, timedelta(minutes=6))


class AlertProjectResolutionTest(TestCase):
    """The project resolver prefers a service+env match, logs
    ambiguity on multi-candidate matches, and falls back deterministically."""

    def setUp(self):
        self.org = Organisations.objects.create(name='AmbiOrg')
        # Two projects both containing a service named "gateway".
        self.p_platform = Project.objects.create(organisation=self.org, name='platform-core')
        self.p_partner = Project.objects.create(organisation=self.org, name='partner-integrations')
        ProjectService.objects.create(project=self.p_platform, name='gateway')
        ProjectService.objects.create(project=self.p_partner, name='gateway')
        ProjectEnvironment.objects.create(
            project=self.p_partner, name='production',
        )

    def _event(self, service='gateway', environment=''):
        return AlertEvent.objects.create(
            organisation=self.org,
            source='alertmanager',
            alertname='HighErrorRate',
            state='firing',
            service=service,
            environment=environment,
        )

    def test_env_match_beats_ambiguity(self):
        """Both projects have ``gateway``, only ``partner-integrations``
        has a ``production`` env — env match wins."""
        from Data.tasks import _resolve_alert_project
        event = self._event(environment='production')
        resolved = _resolve_alert_project(event)
        self.assertEqual(resolved, self.p_partner)

    def test_ambiguous_service_only_match_logs_warning(self):
        """No env context → both projects tie on service name → we
        MUST log the ambiguity so the operator can add a distinguisher."""
        from Data.tasks import _resolve_alert_project
        event = self._event(environment='')
        with self.assertLogs('Data.tasks', level='WARNING') as cm:
            resolved = _resolve_alert_project(event)
        # Deterministic pick (lowest id).
        self.assertEqual(
            resolved.id, min(self.p_platform.id, self.p_partner.id),
        )
        # And the ambiguity was announced.
        self.assertTrue(
            any('projects match service=gateway' in r.getMessage() for r in cm.records),
            'Expected an ambiguity WARNING; got: ' +
            '\n'.join(r.getMessage() for r in cm.records),
        )

    def test_no_service_match_falls_back_with_warning(self):
        """A weak fallback is still worth surfacing at WARNING."""
        from Data.tasks import _resolve_alert_project
        event = self._event(service='no-such-service')
        with self.assertLogs('Data.tasks', level='WARNING') as cm:
            resolved = _resolve_alert_project(event)
        self.assertIsNotNone(resolved)
        self.assertTrue(any('falling back' in r.getMessage() for r in cm.records))

    def test_empty_org_returns_none(self):
        """Nothing to route to — no crash, no warning about a route that
        doesn't exist."""
        from Data.tasks import _resolve_alert_project
        other_org = Organisations.objects.create(name='EmptyOrg')
        event = AlertEvent.objects.create(
            organisation=other_org,
            source='alertmanager',
            alertname='X', state='firing',
            service='anything',
        )
        self.assertIsNone(_resolve_alert_project(event))


# ---------------------------------------------------------------------------
# Q5-3 — service-owner override for slow_span_after_deploy
# ---------------------------------------------------------------------------


class ServicePathOverrideTest(TestCase):
    """Owner-declared globs override the fragile directory heuristic
    and beat cases where the heuristic silently misses."""

    _TRACES = {
        'top_slow': [{
            'service_name': 'checkout',
            'operation_name': 'GET /',
            'trace_id': 'a' * 32,
            'duration_ms': 500,
        }],
        'services_touched': ['checkout'],
    }

    def test_heuristic_still_works_without_override(self):
        """No override → the directory heuristic must still fire on a
        conventional monorepo layout."""
        corrs = correlate_spans_with_code_changes(
            self._TRACES,
            [{'sha': 'aa' * 20, 'files': ['services/checkout/api.py']}],
        )
        self.assertEqual(len(corrs), 1)
        self.assertIn('checkout', corrs[0]['services_affected'])

    def test_package_layout_fails_heuristic(self):
        """A ``pkg-checkout/api.py`` layout doesn't contain
        ``/checkout/`` — the heuristic misses. Documented failure
        mode; this test pins it as such."""
        corrs = correlate_spans_with_code_changes(
            self._TRACES,
            [{'sha': 'bb' * 20, 'files': ['pkg-checkout/api.py']}],
        )
        self.assertEqual(corrs, [])

    def test_owner_glob_catches_package_layout(self):
        """Same package layout, but now the owner declared globs →
        the correlation fires."""
        corrs = correlate_spans_with_code_changes(
            self._TRACES,
            [{'sha': 'cc' * 20, 'files': ['pkg-checkout/api.py']}],
            service_paths_by_name={'checkout': ['pkg-checkout/*']},
        )
        self.assertEqual(len(corrs), 1)
        self.assertIn('checkout', corrs[0]['services_affected'])

    def test_owner_glob_is_authoritative_not_additive(self):
        """When a service has a declared override, the directory
        heuristic is SKIPPED. This lets an owner explicitly EXCLUDE
        a file the heuristic would otherwise match — e.g. shared
        ``services/checkout/README.md`` docs aren't code."""
        corrs = correlate_spans_with_code_changes(
            self._TRACES,
            [{'sha': 'dd' * 20, 'files': ['services/checkout/README.md']}],
            service_paths_by_name={'checkout': ['services/checkout/*.py']},
        )
        self.assertEqual(corrs, [])   # only .py counted per the glob.

    def test_missing_service_in_override_falls_back_to_heuristic(self):
        """A service the owner didn't declare still gets the heuristic —
        so partial adoption doesn't break coverage on undeclared
        services."""
        traces = {
            'top_slow': [
                {'service_name': 'checkout', 'operation_name': 'a',
                 'trace_id': 'a' * 32, 'duration_ms': 500},
                {'service_name': 'inventory', 'operation_name': 'b',
                 'trace_id': 'b' * 32, 'duration_ms': 400},
            ],
            'services_touched': ['checkout', 'inventory'],
        }
        corrs = correlate_spans_with_code_changes(
            traces,
            [{'sha': 'ee' * 20, 'files': ['services/inventory/api.py']}],
            service_paths_by_name={'checkout': ['pkg-checkout/*']},
        )
        self.assertEqual(len(corrs), 1)
        # Inventory came through via the heuristic since it had no override.
        self.assertIn('inventory', corrs[0]['services_affected'])


# ---------------------------------------------------------------------------
# Q5-4 — timeline pagination
# ---------------------------------------------------------------------------


class TimelinePaginationTest(TestCase):
    """The helper accepts ``offset`` and returns a pre-slice total."""

    def setUp(self):
        self.org = Organisations.objects.create(name='TLOrg')
        self.project = Project.objects.create(organisation=self.org, name='tl-proj')
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='tl-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now(),
            data={
                'logs': [
                    {'_source': {
                        '@timestamp': (timezone.now() - timedelta(minutes=i)).isoformat(),
                        'message': f'error {i}',
                        'log_level': 'ERROR',
                        'service': {'name': 'checkout'},
                        'host': {'name': 'host-a'},
                    }}
                    for i in range(50)
                ],
            },
        )

    def test_default_page_returns_first_slice_with_total(self):
        events, total = build_unified_timeline_with_total(
            self.batch, max_events=10, offset=0,
        )
        self.assertEqual(len(events), 10)
        self.assertEqual(total, 50)

    def test_offset_walks_the_timeline(self):
        page1, total1 = build_unified_timeline_with_total(
            self.batch, max_events=10, offset=0,
        )
        page2, total2 = build_unified_timeline_with_total(
            self.batch, max_events=10, offset=10,
        )
        self.assertEqual(len(page1), 10)
        self.assertEqual(len(page2), 10)
        self.assertEqual(total1, total2)
        # Non-overlapping pages. Compare on the (time, summary) tuple —
        # the raw event dict has a nested detail block that's not
        # hashable, but (time, summary) is unique per log event.
        page1_ids = {(e.get('time'), e.get('summary')) for e in page1}
        page2_ids = {(e.get('time'), e.get('summary')) for e in page2}
        self.assertEqual(page1_ids & page2_ids, set())

    def test_offset_past_end_returns_empty_but_total_intact(self):
        events, total = build_unified_timeline_with_total(
            self.batch, max_events=10, offset=500,
        )
        self.assertEqual(events, [])
        self.assertEqual(total, 50)


class TimelineViewPaginationTest(APITestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='TLVOrg')
        self.user = User.objects.create_user(
            username='tlv', email='tlv@test.local',
            password='X', organisation=self.org,
            role='admin', is_active=True,
        )
        self.project = Project.objects.create(organisation=self.org, name='tlv-proj')
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='tlv-batch',
            project=self.project,
            organisation=self.org,
            timestamp=timezone.now(),
            data={
                'logs': [
                    {'_source': {
                        '@timestamp': (timezone.now() - timedelta(minutes=i)).isoformat(),
                        'message': f'error {i}',
                        'log_level': 'ERROR',
                        'service': {'name': 'checkout'},
                        'host': {'name': 'host-a'},
                    }}
                    for i in range(30)
                ],
            },
        )
        self.client.force_authenticate(user=self.user)

    def test_response_includes_pagination_envelope(self):
        resp = self.client.get(f'/api/data/batches/{self.batch.batch_id}/timeline/')
        self.assertEqual(resp.status_code, 200, resp.content)
        pag = resp.data.get('pagination')
        self.assertIsNotNone(pag)
        self.assertEqual(pag['offset'], 0)
        self.assertIn('total_events', pag)
        self.assertIn('has_more', pag)

    def test_limit_and_offset_query_params(self):
        resp = self.client.get(
            f'/api/data/batches/{self.batch.batch_id}/timeline/'
            '?limit=5&offset=10',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['events']), 5)
        self.assertEqual(resp.data['pagination']['offset'], 10)
        self.assertEqual(resp.data['pagination']['limit'], 5)
        # Has more, since only 15 of 30 have been consumed.
        self.assertTrue(resp.data['pagination']['has_more'])

    def test_legacy_max_events_alias_still_works(self):
        """Backwards compat — the pre-Q5 frontend passed ``max_events``."""
        resp = self.client.get(
            f'/api/data/batches/{self.batch.batch_id}/timeline/'
            '?max_events=7',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['events']), 7)
