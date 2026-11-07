"""Similar past incidents without an env key — external review (v1.2.13).

The review found that similarity only worked with an ``OPENAI_API_KEY``
environment variable: without it, embeddings were SHA-256 hashes, so similar
text never matched (Ollama and air-gapped users included); that the env var
contradicted the README's "no env keys" promise; that the prompt memory was
the most recent resolved issues, not the most similar; and that vectors were
stored without their model.
"""

import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from Data.embeddings import (
    LEXICAL_MIN_SIMILARITY, LEXICAL_MODEL, Embedding, SimilarityQuery,
    cosine_similarity, embed_text, lexical_embed, lexical_similarity,
    vectors_comparable,
)
from Data.memory import find_past_memories, query_text_for_batch
from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from org_settings.models import AIModelProvider, OrganisationAISettings, OrganisationAPIKey
from Projects.models import Project


POOL_PAST = ('Database connection pool exhausted in checkout service under load. '
             'Increase pool size and add a connection timeout.')
POOL_NOW = ('The checkout service ran out of DB connections: connection pool '
            'exhaustion. Raise max pool connections.')
UNRELATED = 'TLS certificate expired on the payment gateway ingress; renew it.'


class LexicalSimilarityTest(TestCase):

    def test_similar_incidents_match_without_any_env_key(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            self.assertGreaterEqual(lexical_similarity(POOL_PAST, POOL_NOW),
                                    LEXICAL_MIN_SIMILARITY + 0.2)

    def test_dissimilar_incidents_do_not_match(self):
        self.assertLess(lexical_similarity(POOL_PAST, UNRELATED), LEXICAL_MIN_SIMILARITY / 2)

    def test_ids_and_numbers_do_not_change_the_vector(self):
        a = 'Timeout calling payments for order 81723 (req 9f8e7d6c5b4a)'
        b = 'Timeout calling payments for order 11 (req 00aa11bb22cc)'
        self.assertAlmostEqual(lexical_similarity(a, b), 1.0, places=4)

    def test_camel_case_and_snake_case_agree(self):
        self.assertGreater(
            lexical_similarity('ConnectionPoolTimeout in checkout',
                               'connection_pool timeout in checkout'), 0.9)

    def test_env_openai_key_is_never_read(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-env-should-not-be-used'}), \
                patch('openai.OpenAI') as client:
            result = embed_text(POOL_PAST)
        client.assert_not_called()
        self.assertEqual(result.model, LEXICAL_MODEL)


class DimensionAndModelGuardTest(TestCase):

    def test_cosine_of_mismatched_dimensions_is_zero_not_an_error(self):
        self.assertEqual(cosine_similarity([0.1] * 1536, [0.1] * 768), 0.0)

    def test_vectors_from_different_models_are_not_comparable(self):
        v = [0.1] * 8
        self.assertFalse(vectors_comparable('openai:a', v, 'ollama:b', v))
        self.assertFalse(vectors_comparable('openai:a', v, 'openai:a', [0.1] * 4))
        self.assertFalse(vectors_comparable(None, v, None, v))
        self.assertTrue(vectors_comparable('openai:a', v, 'openai:a', list(v)))

    def test_candidate_from_another_model_is_compared_on_its_text(self):
        query = Embedding(vector=[1.0, 0.0, 0.0], model='openai:text-embedding-3-small')
        candidate = SimpleNamespace(
            embedding=[1.0, 0.0], embedding_model='ollama:nomic-embed-text',
            root_cause=POOL_PAST, recommendation='', description='',
            component='checkout', issue_type='CONNECTION_TIMEOUT',
        )
        sim, relevance = SimilarityQuery(POOL_NOW, query).score(candidate)
        self.assertAlmostEqual(sim, lexical_similarity(POOL_NOW, POOL_PAST + ' checkout '
                                                       'CONNECTION_TIMEOUT'), delta=0.1)
        self.assertGreaterEqual(relevance, 0)


@override_settings(SEROPS_EMBEDDINGS_VIA_PROVIDER=True)
class OrgProviderEmbeddingTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='EmbedOrg')

    def _use(self, provider_name, api_key='', base_url=None, extra=None):
        provider = AIModelProvider.objects.get(name=provider_name)
        OrganisationAISettings.objects.create(organisation=self.org, default_provider=provider)
        OrganisationAPIKey.objects.create(
            organisation=self.org, provider=provider, api_key=api_key,
            base_url=base_url, extra_config=extra or {},
        )

    @staticmethod
    def _openai_client(vector):
        client = MagicMock()
        client.embeddings.create.return_value = SimpleNamespace(
            data=[SimpleNamespace(embedding=vector)])
        return client

    def test_openai_org_key_is_used_for_embeddings(self):
        self._use('openai', api_key='sk-org-key')
        client = self._openai_client([3.0, 4.0])
        with patch('openai.OpenAI', return_value=client) as ctor:
            result = embed_text(POOL_PAST, organisation=self.org)
        self.assertEqual(ctor.call_args.kwargs['api_key'], 'sk-org-key')
        self.assertEqual(client.embeddings.create.call_args.kwargs['model'],
                         'text-embedding-3-small')
        self.assertEqual(result.model, 'openai:text-embedding-3-small')
        self.assertAlmostEqual(result.vector[0], 0.6)

    def test_ollama_needs_no_key_and_uses_its_own_url(self):
        self._use('ollama', base_url='http://ollama.internal:11434/v1/')
        client = self._openai_client([1.0, 0.0])
        with patch('openai.OpenAI', return_value=client) as ctor:
            result = embed_text(POOL_PAST, organisation=self.org)
        self.assertEqual(ctor.call_args.kwargs['base_url'], 'http://ollama.internal:11434/v1/')
        self.assertEqual(result.model, 'ollama:nomic-embed-text')

    def test_embedding_model_can_be_overridden_per_key(self):
        self._use('ollama', base_url='http://ollama:11434/v1/',
                  extra={'embedding_model': 'mxbai-embed-large'})
        client = self._openai_client([1.0])
        with patch('openai.OpenAI', return_value=client):
            result = embed_text(POOL_PAST, organisation=self.org)
        self.assertEqual(result.model, 'ollama:mxbai-embed-large')

    def test_gemini_org_key_is_used_for_embeddings(self):
        self._use('gemini', api_key='g-org-key')
        client = MagicMock()
        client.models.embed_content.return_value = SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.0, 2.0])])
        with patch('google.genai.Client', return_value=client) as ctor:
            result = embed_text(POOL_PAST, organisation=self.org)
        self.assertEqual(ctor.call_args.kwargs['api_key'], 'g-org-key')
        self.assertEqual(result.model, 'gemini:gemini-embedding-001')
        self.assertEqual(result.vector, [0.0, 1.0])

    def test_claude_only_org_embeds_locally_without_any_http_call(self):
        self._use('claude', api_key='sk-ant')
        with patch('openai.OpenAI') as ctor:
            result = embed_text(POOL_PAST, organisation=self.org)
        ctor.assert_not_called()
        self.assertEqual(result.model, LEXICAL_MODEL)

    def test_provider_failure_falls_back_to_lexical(self):
        self._use('openai', api_key='sk-org-key')
        client = MagicMock()
        client.embeddings.create.side_effect = RuntimeError('503')
        with patch('openai.OpenAI', return_value=client):
            result = embed_text(POOL_PAST, organisation=self.org)
        self.assertEqual(result.model, LEXICAL_MODEL)

    def test_resolve_task_stores_vector_with_its_model(self):
        from Data.tasks import embed_resolved_issue
        self._use('openai', api_key='sk-org-key')
        batch = AIAnalyzedBatch.objects.create(batch_id='embed-task', organisation=self.org)
        issue = Issue.objects.create(
            batch=batch, organisation=self.org, severity='HIGH', fingerprint='et',
            issue_type='CONNECTION_TIMEOUT', root_cause=POOL_PAST, status='OPEN',
        )
        with patch('openai.OpenAI', return_value=self._openai_client([1.0, 0.0])):
            embed_resolved_issue.apply(args=[issue.pk])
        issue.refresh_from_db()
        self.assertEqual(issue.embedding_model, 'openai:text-embedding-3-small')
        self.assertEqual(issue.embedding, [1.0, 0.0])


class PromptMemoryPicksTheMostSimilarTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='MemSimOrg')
        self.project = Project.objects.create(name='shop', organisation=self.org)
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='mem-sim', project=self.project, organisation=self.org,
            environment='production',
            data={'logs': [
                {'_source': {'level': 'ERROR', 'service_name': 'checkout',
                             'message': 'psycopg2.OperationalError: connection pool '
                                        'exhausted (pool size 10)'}},
                {'_source': {'level': 'ERROR', 'service_name': 'checkout',
                             'message': 'timeout acquiring DB connection from pool'}},
                {'_source': {'level': 'INFO', 'message': 'GET /health 200'}},
            ]},
        )

    def _resolved(self, root_cause, component, days_ago, fp):
        return Issue.objects.create(
            batch=self.batch, project=self.project, organisation=self.org,
            environment='production', severity='CRITICAL', fingerprint=fp,
            issue_type='INCIDENT', component=component, root_cause=root_cause,
            recommendation='', status='RESOLVED',
            resolved_at=timezone.now() - timedelta(days=days_ago),
        )

    def test_similar_older_issue_beats_recent_unrelated_ones(self):
        similar = self._resolved(
            'Database connection pool exhausted in checkout under peak load',
            'checkout', days_ago=40, fp='sim')
        recent = [
            self._resolved('TLS certificate expired on the payment gateway ingress',
                           'ingress', days_ago=1, fp='r1'),
            self._resolved('Redis OOM killed after a memory leak in cart cache eviction',
                           'cart', days_ago=2, fp='r2'),
            self._resolved('Kubernetes CrashLoopBackOff because a ConfigMap key was missing',
                           'frontend', days_ago=3, fp='r3'),
        ]
        memories = find_past_memories(
            self.project, 'production', self.org,
            query_text=query_text_for_batch(self.batch),
        )
        ids = [issue.id for issue, _tier in memories]
        self.assertEqual(ids[0], similar.id)
        # Only a small recency slice of non-matching issues fills the rest.
        self.assertEqual(len(ids), 2)
        self.assertEqual(ids[1], recent[0].id)

    def test_batch_digest_prefers_error_lines_and_folds_repeats(self):
        self.batch.data['logs'].append(
            {'_source': {'level': 'ERROR', 'service_name': 'checkout',
                         'message': 'psycopg2.OperationalError: connection pool '
                                    'exhausted (pool size 12)'}})
        digest = query_text_for_batch(self.batch)
        self.assertIn('checkout: psycopg2.OperationalError', digest)
        self.assertNotIn('/health', digest)
        self.assertEqual(digest.count('OperationalError'), 1)

    def test_without_a_query_memory_keeps_the_recency_order(self):
        old = self._resolved('Database connection pool exhausted in checkout under load',
                             'checkout', days_ago=40, fp='o')
        new = self._resolved('TLS certificate expired on the payment gateway ingress',
                             'ingress', days_ago=1, fp='n')
        ids = [i.id for i, _ in find_past_memories(self.project, 'production', self.org)]
        self.assertEqual(ids, [new.id, old.id])

    def test_stored_vector_of_another_dimension_does_not_break_memory(self):
        issue = self._resolved('Database connection pool exhausted in checkout under load',
                               'checkout', days_ago=5, fp='dim')
        Issue.objects.filter(pk=issue.pk).update(embedding=[0.5] * 7,
                                                 embedding_model='openai:old-model')
        memories = find_past_memories(self.project, 'production', self.org,
                                      query_text=query_text_for_batch(self.batch))
        self.assertEqual([i.id for i, _ in memories], [issue.id])
