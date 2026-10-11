"""Shared setup + fake-AI helper for e2e tests.

The base class provisions the minimum realistic tenant — one org, one
admin user, one project with one service — so every test file can start
from a running organisation without repeating the fixture code. It also
pre-loads the API client with force_authenticate so tests can call REST
endpoints without paying for a login round-trip on every request.

The AI provider is the only layer we stub. `fake_ai_json` returns a
dict shaped exactly like a parsed AI response — same field names, same
enum casing, same JSON schema the pipeline reads in production. That
lets the analyzer, deduplicator, serialiser, and read API all run for
real; only the network hop to Claude/OpenAI/Gemini is skipped.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Projects.models import Project, ProjectService
from Users.models import User


def fake_ai_json(
    correlated_issues: list[dict] | None = None,
    *,
    overall_health: str = 'DEGRADED',
    data_sources_available: list[str] | None = None,
    total_entries: int = 100,
) -> dict:
    """Return a parsed-AI-response dict matching ``_JSON_TEMPLATE``.

    Only the ``correlated_issues`` list is worth customising in tests;
    everything else has a defensible default that survives the
    downstream pipeline unchanged. Callers pass a list of issue dicts;
    each issue may omit any field and gets a full-shaped default filled
    in. That keeps test setUps short without letting the analyzer see
    a partial JSON that the real Claude/OpenAI/Gemini output would
    never produce.
    """
    if correlated_issues is None:
        correlated_issues = [{}]
    if data_sources_available is None:
        data_sources_available = ['logs']

    now_iso = timezone.now().isoformat()
    filled_issues = [_default_issue(i) for i in correlated_issues]

    return {
        'summary': {
            'total_entries': total_entries,
            'time_range': {'start': now_iso, 'end': now_iso},
            'overall_health': overall_health,
            'data_sources_available': data_sources_available,
        },
        'correlated_issues': filled_issues,
        'recommendations': [
            {
                'priority': 'HIGH',
                'action': 'Investigate the root cause identified above.',
                'type': 'IMMEDIATE',
                'based_on': list(data_sources_available),
            },
        ],
    }


def _default_issue(overrides: dict) -> dict:
    """Fill an issue dict with values the deduplicator will accept."""
    base = {
        'issue_type': 'CONNECTION_REFUSED',
        'scope': 'SERVICE',
        'component': 'checkout',
        'severity': 'CRITICAL',
        'error_class': 'CONNECTION_REFUSED',
        'error_target': 'redis:6379',
        'description': 'Connection refused to redis:6379 from checkout service.',
        'root_cause': (
            'Redis pod was recycled by the cluster autoscaler; the '
            'connection pool did not fail over to the new endpoint.'
        ),
        'recommended_action': (
            'Add liveness probe with restart-on-failure to the checkout '
            'deployment.'
        ),
        'reasoning': [
            'Observed ConnectionRefusedError log entries from checkout.',
            'No matching incident in the last 24 h in the deduplication table.',
            'Cross-checked deploy timeline — no code change in the window.',
        ],
        'confidence': 'HIGH',
        'evidence_sources': {
            'logs': ['ConnectionRefusedError [Errno 111]'],
        },
    }
    base.update(overrides)
    return base


class E2ETestCase(APITestCase):
    """Realistic single-tenant setUp shared by every e2e test file.

    Provisions one primary org (with an admin user, a project, and a
    service) plus a second unrelated org (with its own admin) so
    tenant-isolation assertions can run cheaply. Tests authenticate as
    ``self.admin`` by default; call ``self._auth(self.other_admin)``
    to switch tenants for isolation checks.
    """

    def setUp(self):
        super().setUp()

        self.org = Organisations.objects.create(
            name='E2E Primary', website='https://e2e-primary.test',
        )
        self.other_org = Organisations.objects.create(
            name='E2E Other', website='https://e2e-other.test',
        )

        self.admin = User.objects.create_user(
            username='e2e_admin', email='e2e-admin@test.local',
            password='E2ETest123!', organisation=self.org,
            role='admin', is_active=True,
        )
        self.other_admin = User.objects.create_user(
            username='e2e_other_admin', email='e2e-other@test.local',
            password='E2ETest123!', organisation=self.other_org,
            role='admin', is_active=True,
        )

        self.project = Project.objects.create(
            name='e2e-project', organisation=self.org,
        )
        self.other_project = Project.objects.create(
            name='e2e-other-project', organisation=self.other_org,
        )

        self.service = ProjectService.objects.create(
            project=self.project,
            name='checkout',
        )

        self.client.force_authenticate(user=self.admin)

    def _auth(self, user):
        """Re-authenticate the APIClient as a different user."""
        self.client.force_authenticate(user=user)

    def _fake_generate(
        self,
        analysis: dict[str, Any] | None = None,
        *,
        model_name: str = 'e2e-fake-model',
        tokens_input: int = 500,
        tokens_output: int = 700,
    ):
        """Return a ``(analysis_json_str, model_name, None, tin, tout)`` tuple.

        Matches the exact return shape of
        ``ai_model.ai_service.generate_for_organisation``. Patch
        ``ai_model.tasks.generate_for_organisation`` (not the module
        it lives in) so that the imported reference in tasks.py is
        replaced — ``ai_model.tasks`` binds the name at import time.
        """
        import json
        payload = analysis if analysis is not None else fake_ai_json()
        return (json.dumps(payload), model_name, None, tokens_input, tokens_output)
