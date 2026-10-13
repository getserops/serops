"""
Tests for the seed_demo_org management command.

We cover the shape of the seeded content (what gets created and how
many), the story-arc invariants (centerpiece incident, mix of
statuses, mix of confidence levels, chat sessions), idempotency (the
command can be safely re-run without duplicates or constraint errors),
and isolation (the command never touches data outside the demo org).
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project, ProjectService
from providers.models import Pipeline, CodeChange
from Data.models import AIAnalyzedBatch, Issue
from ai_model.models import ChatSession, ChatMessage, AITokenUsage

from Data.management.commands.seed_demo_org import (
    DEMO_ORG_SLUG,
    DEMO_USER_EMAIL,
    PROJECT_CHECKOUT,
    PROJECT_PLATFORM,
)


class SeedDemoOrgContentShapeTest(TestCase):
    """First run creates exactly the content the demo promises."""

    @classmethod
    def setUpTestData(cls):
        call_command('seed_demo_org', stdout=StringIO())
        cls.org = Organisations.objects.get(slug=DEMO_ORG_SLUG)

    def test_org_is_flagged_is_demo(self):
        self.assertTrue(self.org.is_demo)
        self.assertEqual(self.org.name, 'Acme Cloud')

    def test_demo_user_exists_and_is_flagged(self):
        user = User.objects.get(email=DEMO_USER_EMAIL)
        self.assertTrue(user.is_demo)
        # Demo user is admin (not viewer) so visitors can *see* every
        # admin surface (Team, AI settings, Sentinel, Mail, Audit Log,
        # Escalation Rules). Writes are blocked by DemoUserMiddleware
        # regardless of role — that middleware is the security
        # boundary, not RBAC. See _upsert_user in
        # Data/management/commands/seed_demo_org.py.
        self.assertEqual(user.role, 'admin')
        self.assertTrue(user.is_active)
        self.assertEqual(user.organisation_id, self.org.id)

    def test_two_projects_created(self):
        names = set(
            Project.objects.filter(organisation=self.org).values_list('name', flat=True)
        )
        self.assertEqual(names, {PROJECT_CHECKOUT, PROJECT_PLATFORM})

    def test_five_services_distributed_across_projects(self):
        services = ProjectService.objects.filter(project__organisation=self.org)
        self.assertEqual(services.count(), 5)
        # 3 services in checkout, 2 in platform.
        self.assertEqual(
            services.filter(project__name=PROJECT_CHECKOUT).count(), 3,
        )
        self.assertEqual(
            services.filter(project__name=PROJECT_PLATFORM).count(), 2,
        )

    def test_batches_span_at_least_a_week(self):
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org).order_by('timestamp')
        self.assertGreaterEqual(batches.count(), 9)
        span_days = (batches.last().timestamp - batches.first().timestamp).days
        self.assertGreaterEqual(span_days, 6)

    def test_batches_cover_alert_and_quiet_decisions(self):
        decisions = set(
            AIAnalyzedBatch.objects
            .filter(organisation=self.org)
            .values_list('sentinel_decision', flat=True)
        )
        self.assertIn('alert', decisions)
        self.assertIn('quiet', decisions)

    def test_at_least_one_critical_open_issue(self):
        critical_open = Issue.objects.filter(
            organisation=self.org, severity='CRITICAL', status='OPEN',
        )
        self.assertGreaterEqual(critical_open.count(), 1)

    def test_at_least_one_resolved_issue_with_root_cause(self):
        resolved = Issue.objects.filter(
            organisation=self.org, status='RESOLVED',
        ).exclude(root_cause='').exclude(root_cause=None)
        self.assertGreaterEqual(resolved.count(), 1)
        # Resolution must be descriptive enough to feed Recent
        # Resolutions Context (>= 30 chars matches Data.memory).
        self.assertGreater(len(resolved.first().root_cause), 30)

    def test_at_least_one_muted_issue(self):
        muted = Issue.objects.filter(organisation=self.org, status='MUTED')
        self.assertGreaterEqual(muted.count(), 1)

    def test_issues_carry_reasoning_and_confidence(self):
        issues = Issue.objects.filter(organisation=self.org)
        self.assertTrue(any(i.reasoning for i in issues))
        confidences = set(issues.values_list('confidence', flat=True))
        # At least two different confidence levels — otherwise the
        # demo would look like the AI is always 100% sure.
        self.assertGreaterEqual(len(confidences), 2)

    def test_deployments_have_linked_code_changes(self):
        code_changes = CodeChange.objects.filter(organisation=self.org)
        self.assertGreaterEqual(code_changes.count(), 5)
        # Every code change must be linked to a Pipeline so the
        # dashboard's RecentDeployments card has data to render.
        self.assertTrue(all(cc.pipeline_id for cc in code_changes))

    def test_three_chat_sessions_seeded(self):
        sessions = ChatSession.objects.filter(user__organisation=self.org)
        self.assertEqual(sessions.count(), 3)
        # Each session must have at least one exchange.
        for session in sessions:
            self.assertGreaterEqual(
                ChatMessage.objects.filter(chat_session=session).count(), 1,
            )

    def test_ai_token_usage_recorded_with_real_cost(self):
        """Token usage must be present so the Sentinel cost-saved hero
        widget on the dashboard has real numbers to display."""
        usage = AITokenUsage.objects.filter(organisation=self.org)
        # At least one usage row per analyzed (non-skipped) batch.
        self.assertGreaterEqual(usage.count(), 1)
        # Every row must report a positive cost — otherwise the dollar
        # savings widget would render $0.
        for u in usage:
            self.assertGreater(u.cost_usd, 0)
            self.assertGreater(u.tokens_total, 0)


class SeedDemoOrgIdempotencyTest(TestCase):
    """Running the command twice must not produce duplicates or fail."""

    def test_second_run_produces_same_counts(self):
        call_command('seed_demo_org', stdout=StringIO())
        org = Organisations.objects.get(slug=DEMO_ORG_SLUG)
        first_counts = {
            'projects': Project.objects.filter(organisation=org).count(),
            'services': ProjectService.objects.filter(project__organisation=org).count(),
            'batches': AIAnalyzedBatch.objects.filter(organisation=org).count(),
            'issues': Issue.objects.filter(organisation=org).count(),
            'chats': ChatSession.objects.filter(user__organisation=org).count(),
            'pipelines': Pipeline.objects.filter(organisation=org).count(),
            'commits': CodeChange.objects.filter(organisation=org).count(),
        }

        call_command('seed_demo_org', stdout=StringIO())
        second_counts = {
            'projects': Project.objects.filter(organisation=org).count(),
            'services': ProjectService.objects.filter(project__organisation=org).count(),
            'batches': AIAnalyzedBatch.objects.filter(organisation=org).count(),
            'issues': Issue.objects.filter(organisation=org).count(),
            'chats': ChatSession.objects.filter(user__organisation=org).count(),
            'pipelines': Pipeline.objects.filter(organisation=org).count(),
            'commits': CodeChange.objects.filter(organisation=org).count(),
        }
        self.assertEqual(first_counts, second_counts)


class SeedDemoOrgIsolationTest(TestCase):
    """The command must never touch data outside the demo org."""

    def test_existing_org_data_is_left_untouched(self):
        # An unrelated org with its own project, batch, and issue.
        other_org = Organisations.objects.create(name='Real Customer Inc')
        other_project = Project.objects.create(
            name='real-app', organisation=other_org,
        )
        from django.utils import timezone
        other_batch = AIAnalyzedBatch.objects.create(
            batch_id='real-batch-1', organisation=other_org,
            project=other_project, timestamp=timezone.now(),
            environment='production', data={},
        )
        other_issue = Issue.objects.create(
            batch=other_batch, project=other_project, organisation=other_org,
            severity='WARNING', description='Real customer issue',
            issue_type='OTHER', component='backend',
            environment='production', fingerprint='real-fp-1',
        )

        call_command('seed_demo_org', stdout=StringIO())

        # Nothing about the real org should have changed.
        self.assertTrue(Organisations.objects.filter(pk=other_org.pk).exists())
        self.assertTrue(Project.objects.filter(pk=other_project.pk).exists())
        self.assertTrue(AIAnalyzedBatch.objects.filter(pk=other_batch.pk).exists())
        self.assertTrue(Issue.objects.filter(pk=other_issue.pk).exists())

    def test_dry_run_creates_nothing(self):
        call_command('seed_demo_org', '--dry-run', stdout=StringIO())
        self.assertFalse(
            Organisations.objects.filter(slug=DEMO_ORG_SLUG).exists()
        )


class SeedDemoOrgAIProviderTest(TestCase):
    """The demo org runs on Gemini, end to end.

    The seed used to pin Claude as the demo's primary provider and stamp
    'claude-sonnet-4' on every batch, token-usage row and chat message, while
    the demo's key row is a Gemini one. A visitor opening Settings → AI saw a
    primary provider nothing was configured for.
    The nightly reset re-runs this command, so the seed is the only place the
    choice can live — a database edit would be undone at 02:00.
    """

    @classmethod
    def setUpTestData(cls):
        from org_settings.models import AIModelProvider
        # Present on every real install via migration 0011; created here so
        # the test does not depend on migration data surviving test setup.
        cls.gemini, _ = AIModelProvider.objects.get_or_create(
            name='gemini',
            defaults={'display_name': 'Google Gemini',
                      'default_model': 'gemini-3.6-flash', 'is_active': True},
        )
        AIModelProvider.objects.get_or_create(
            name='claude',
            defaults={'display_name': 'Anthropic Claude',
                      'default_model': 'claude-sonnet-5', 'is_active': True},
        )
        call_command('seed_demo_org', stdout=StringIO())
        cls.org = Organisations.objects.get(is_demo=True)

    def test_primary_provider_is_gemini(self):
        from org_settings.models import OrganisationAISettings
        settings_row = OrganisationAISettings.objects.get(organisation=self.org)
        self.assertEqual(settings_row.default_provider.name, 'gemini')

    def test_story_records_the_gemini_model(self):
        expected = self.gemini.default_model
        batches = AIAnalyzedBatch.objects.filter(organisation=self.org)
        self.assertTrue(batches.exists())
        self.assertEqual(set(batches.values_list('model_name', flat=True)), {expected})
        usage = AITokenUsage.objects.filter(organisation=self.org)
        self.assertTrue(usage.exists())
        self.assertEqual(set(usage.values_list('model_name', flat=True)), {expected})
        msgs = ChatMessage.objects.filter(chat_session__user__organisation=self.org)
        self.assertTrue(msgs.exists())
        for msg in msgs:
            self.assertEqual(msg.metadata.get('ai_model'), expected)

    def test_gemini_key_row_is_decryptable_placeholder(self):
        # The model picker lists providers whose key decrypts; a row
        # encrypted under an older SECRET_KEY decrypts to '' and hid Gemini.
        from ai_model.ai_service import get_api_key_for_org
        from Data.management.commands.seed_demo_org import SEED_DEMO_PLACEHOLDER
        api_key, _, _ = get_api_key_for_org(self.org, 'gemini')
        self.assertEqual(api_key, SEED_DEMO_PLACEHOLDER)

    def test_reseed_replaces_an_undecryptable_key(self):
        from org_settings.models import OrganisationAPIKey
        from ai_model.ai_service import get_api_key_for_org
        OrganisationAPIKey.objects.filter(organisation=self.org, provider=self.gemini).update(
            api_key='gAAAAAencrypted-under-a-rotated-secret-key',
        )
        self.assertFalse(get_api_key_for_org(self.org, 'gemini')[0])
        call_command('seed_demo_org', stdout=StringIO())
        self.assertTrue(get_api_key_for_org(self.org, 'gemini')[0])

    def test_available_models_lists_gemini_for_the_demo_user(self):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(User.objects.get(organisation=self.org, is_demo=True))
        response = client.get('/api/settings/ai/available-models/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('gemini', [m['id'] for m in response.json()['models']])

    def test_model_follows_the_catalogue(self):
        # Read at seed time, so a default-model migration flows through
        # instead of the story going stale on a retired model name.
        self.gemini.default_model = 'gemini-9-test'
        self.gemini.save()
        call_command('seed_demo_org', stdout=StringIO())
        models = set(AIAnalyzedBatch.objects.filter(organisation=self.org)
                     .values_list('model_name', flat=True))
        self.assertEqual(models, {'gemini-9-test'})
