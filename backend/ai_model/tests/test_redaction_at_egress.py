"""Every AI call is redacted at the single choke point, and fails closed.

External review (v1.2.13): "'Only redacted context goes to the AI provider'
is false. Chat, reanalysis and model comparison, CI/CD errors and
post-mortem commit messages skip redaction. If redaction fails on logs,
they go out unredacted."

Redaction now happens in ``generate_text_unified``, which every AI path
goes through. These tests swap in a fake adapter (the last hop before the
provider SDK) and assert on what it RECEIVES, one test per path — so a new
path that bypasses ``generate_text_unified`` or a regression in it shows up
here, not in a provider's logs.
"""

from __future__ import annotations

import json
import logging
import uuid
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from Data.models import AIAnalyzedBatch
from Organisations.models import Organisations
from Projects.models import Project

# Secrets the review found leaking, plus the old classics. None of these
# strings may reach the adapter.
DOCKER_PW = 'S3cr3tPassw0rd'
ANTHROPIC_KEY = 'sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-abcdEFGH'
BASIC_B64 = 'dXNlcjpwYXNzd29yZA=='
SECRET_LINE = (
    f'docker login -u ci -p {DOCKER_PW} registry.example.com; '
    f'key {ANTHROPIC_KEY}; Authorization: Basic {BASIC_B64}; '
    'mot de passe: hunter2; peer 203.0.113.45'
)
LEAKS = (DOCKER_PW, ANTHROPIC_KEY, BASIC_B64, 'hunter2', '203.0.113.45')

OK_JSON = json.dumps({'summary': {'overall_health': 'WARNING'},
                      'correlated_issues': [], 'recommendations': []})


class _RecordingAdapter:
    """Stands in for the provider adapter and records what it was sent."""

    def __init__(self, response=OK_JSON):
        self.calls = []
        self.response = response

    def generate(self, prompt, config, api_key=None, system_prefix=None):
        self.calls.append({'prompt': prompt, 'system_prefix': system_prefix})
        return self.response, None, 10, 5


class _EgressFixture(TestCase):

    def setUp(self):
        self.adapter = _RecordingAdapter()
        patcher = patch('ai_model.adapters.registry.AdapterRegistry.get_adapter',
                        return_value=self.adapter)
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent(self):
        """Everything the adapter received, as one string."""
        return '\n'.join(f"{c['system_prefix'] or ''}\n{c['prompt'] or ''}"
                         for c in self.adapter.calls)

    def assertNothingLeaked(self):
        self.assertTrue(self.adapter.calls, 'the adapter was never called')
        sent = self.sent()
        for secret in LEAKS:
            self.assertNotIn(secret, sent)

    def make_org_with_ai(self, name='Egress org'):
        from org_settings.models import AIModelProvider, OrganisationAISettings
        org = Organisations.objects.create(name=f'{name} {uuid.uuid4().hex[:6]}')
        claude, _ = AIModelProvider.objects.get_or_create(name='claude')
        OrganisationAISettings.objects.create(organisation=org, default_provider=claude)
        key = patch('ai_model.ai_service.get_api_key_for_org', return_value=('k', None, {}))
        key.start()
        self.addCleanup(key.stop)
        return org


class GenerateTextUnifiedRedactsTest(_EgressFixture):

    def test_the_prompt_reaches_the_adapter_redacted(self):
        from ai_model.ai_service import generate_text_unified
        response, error, _, _ = generate_text_unified(SECRET_LINE, provider='claude', api_key='k')
        self.assertIsNone(error)
        self.assertNothingLeaked()
        self.assertIn('docker login -u ci -p *****', self.sent())

    def test_the_system_prefix_reaches_the_adapter_redacted(self):
        from ai_model.ai_service import generate_text_unified
        generate_text_unified('hello', provider='claude', api_key='k', system_prefix=SECRET_LINE)
        self.assertNothingLeaked()

    def test_the_static_batch_system_prompt_is_not_changed_by_redaction(self):
        """The system prompt is our own text: redaction must leave it alone, or
        the instructions the model reads differ from the ones we wrote."""
        from ai_model.prompts import get_batch_analysis_system_prompt
        from Utils.redaction_helpers import redact_for_ai
        system = get_batch_analysis_system_prompt()
        self.assertEqual(redact_for_ai(system), system)

    def test_already_redacted_text_is_sent_unchanged(self):
        from ai_model.ai_service import generate_text_unified
        from Utils.redaction_helpers import redact_for_ai
        once = redact_for_ai(SECRET_LINE)
        generate_text_unified(once, provider='claude', api_key='k')
        self.assertEqual(self.adapter.calls[0]['prompt'], once)


class FailClosedTest(_EgressFixture):

    def test_a_redaction_error_sends_nothing_and_returns_redaction_failed(self):
        from ai_model.ai_service import generate_text_unified
        with patch('Utils.data_redaction.DataRedactionService.redact',
                   side_effect=RuntimeError(f'boom near {DOCKER_PW}')), \
                self.assertLogs('ai_model.ai_service', level=logging.ERROR) as logs:
            response, error, t_in, t_out = generate_text_unified(
                SECRET_LINE, provider='claude', api_key='k')
        self.assertEqual(self.adapter.calls, [], 'nothing may reach the provider')
        self.assertIsNone(response)
        self.assertEqual(error.code, 'REDACTION_FAILED')
        self.assertEqual((t_in, t_out), (0, 0))
        # The exception message can quote the text being redacted.
        self.assertNotIn(DOCKER_PW, '\n'.join(logs.output))

    def test_a_prompt_that_is_not_a_string_is_refused_not_sent_unscanned(self):
        from ai_model.ai_service import generate_text_unified
        _, error, _, _ = generate_text_unified([SECRET_LINE], provider='claude', api_key='k')
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(error.code, 'REDACTION_FAILED')

    def test_a_redaction_failure_on_the_org_path_does_not_fall_back_to_sending(self):
        from ai_model.ai_service import generate_for_organisation
        org = self.make_org_with_ai()
        with patch('Utils.data_redaction.DataRedactionService.redact',
                   side_effect=RuntimeError('boom')):
            response, _, error, _, _ = generate_for_organisation(SECRET_LINE, org)
        self.assertIsNone(response)
        self.assertEqual(self.adapter.calls, [])
        self.assertEqual(error.code, 'REDACTION_FAILED')

    def test_a_redaction_failure_in_embeddings_falls_back_to_lexical(self):
        from Data import embeddings
        from org_settings.models import AIModelProvider, OrganisationAISettings, OrganisationAPIKey
        org = Organisations.objects.create(name=f'emb-{uuid.uuid4().hex[:6]}')
        openai = AIModelProvider.objects.get(name='openai')
        OrganisationAISettings.objects.create(organisation=org, default_provider=openai)
        OrganisationAPIKey.objects.create(organisation=org, provider=openai, api_key='sk-org-key')
        with patch('Utils.data_redaction.DataRedactionService.redact',
                   side_effect=RuntimeError('boom')), \
                patch('openai.OpenAI') as client:
            result = embeddings.embed_text(SECRET_LINE, organisation=org)
        client.assert_not_called()
        self.assertTrue(result.is_lexical)


class EveryAIPathIsRedactedTest(_EgressFixture):
    """One test per path the review listed."""

    def _batch(self, org, data):
        return AIAnalyzedBatch.objects.create(
            batch_id=f'egress-{uuid.uuid4().hex[:8]}', organisation=org,
            project=Project.objects.create(name=f'p-{uuid.uuid4().hex[:6]}', organisation=org),
            timestamp=timezone.now(), environment='production', data=data,
        )

    def test_chat(self):
        from ai_model.views import process_ai_request
        process_ai_request(f'why did it fail? {SECRET_LINE}', 'claude')
        self.assertNothingLeaked()

    def test_reanalysis_and_model_comparison(self):
        from ai_model.tasks import reanalyze_batch_with_model
        org = self.make_org_with_ai()
        batch = self._batch(org, {'logs': [{'_source': {
            '@timestamp': '2026-11-03T10:00:00Z', 'level': 'ERROR', 'service': 'ci',
            'message': SECRET_LINE}}], 'metrics_summary': {}})
        with patch('ai_model.tasks.get_api_key_for_org', return_value=('k', None, {})):
            for mode in ('compare', 'primary'):
                reanalyze_batch_with_model.run(batch.batch_id, 'claude', mode=mode)
        self.assertEqual(len(self.adapter.calls), 2)
        self.assertNothingLeaked()

    def test_batch_analysis_with_cicd_job_errors_and_commit_messages(self):
        from ai_model.tasks import analyze_batch
        org = self.make_org_with_ai()
        batch = self._batch(org, {
            'logs': [{'_source': {'message': 'build failed', 'level': 'ERROR', 'service': 'ci'}}],
            'metrics': {}, 'metrics_summary': {},
            'code_changes': [{'sha': 'abcd1234ef', 'author': 'dev', 'message': SECRET_LINE,
                              'timestamp': '2026-11-03T09:00:00Z'}],
            'cicd_logs': [{'status': 'failed', 'job_name': 'push', 'branch': 'main',
                           'pipeline_id': 7, 'trace_errors': SECRET_LINE}],
            'statistics': {'total_logs': 1, 'total_metrics': 0,
                           'total_code_changes': 1, 'total_cicd_logs': 1},
        })
        analyze_batch(batch.batch_id)
        self.assertNothingLeaked()

    def test_postmortem_commit_messages(self):
        from ai_model.postmortem import generate_postmortem_draft
        org = self.make_org_with_ai()
        self.adapter.response = '# Post-mortem\n\n## Summary\n' + 'long enough markdown body ' * 20
        batch = self._batch(org, {'code_changes': [{
            'sha': 'abcd1234', 'author': 'dev', 'message': f'ci: docker login -p {DOCKER_PW}; {ANTHROPIC_KEY}',
            'timestamp': '2026-11-03T09:00:00Z'}]})
        generate_postmortem_draft(batch)
        self.assertTrue(self.adapter.calls)
        self.assertNotIn(DOCKER_PW, self.sent())
        self.assertNotIn(ANTHROPIC_KEY, self.sent())

    def test_model_fallback_helper(self):
        from ai_model.ai_service import generate_with_fallback
        generate_with_fallback(SECRET_LINE, primary='claude', fallback=None, primary_key='k')
        self.assertNothingLeaked()
