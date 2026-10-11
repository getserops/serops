"""Tests for Item #27 (similar-incidents via embeddings) + Item #28
(post-mortem draft generator)."""

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Data.embeddings import (
    EMBEDDING_DIM, _hash_embed, _l2_normalize, cosine_similarity,
    embed_text, text_for_issue,
)
from Data.models import AIAnalyzedBatch, Issue
from Organisations.models import Organisations
from Projects.models import Project

User = get_user_model()


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------


class EmbeddingBackendTest(TestCase):

    def test_hash_embed_deterministic(self):
        a = _hash_embed('connection pool exhausted in checkout service')
        b = _hash_embed('connection pool exhausted in checkout service')
        self.assertEqual(len(a), EMBEDDING_DIM)
        self.assertEqual(a, b)

    def test_hash_embed_different_text_different_vector(self):
        a = _hash_embed('one')
        b = _hash_embed('two')
        self.assertNotEqual(a, b)

    def test_l2_normalize(self):
        v = _l2_normalize([3.0, 4.0])
        norm = (v[0] ** 2 + v[1] ** 2) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_l2_normalize_zero_vector(self):
        self.assertEqual(_l2_normalize([0.0, 0.0]), [0.0, 0.0])

    def test_cosine_identical_is_one(self):
        v = _hash_embed('same text')
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=5)

    def test_cosine_zero_for_orthogonal(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [0, 1]), 0.0, places=5)

    def test_cosine_zero_vector(self):
        self.assertEqual(cosine_similarity([0, 0], [1, 1]), 0.0)

    def test_embed_text_empty_returns_none(self):
        self.assertIsNone(embed_text(''))
        self.assertIsNone(embed_text('   '))

    def test_embed_text_falls_back_when_no_openai(self):
        # Ensure no key set.
        prev = os.environ.pop('OPENAI_API_KEY', None)
        try:
            v = embed_text('the checkout service is timing out')
            self.assertIsNotNone(v)
            self.assertEqual(len(v), EMBEDDING_DIM)
        finally:
            if prev is not None:
                os.environ['OPENAI_API_KEY'] = prev


# ---------------------------------------------------------------------------
# text_for_issue
# ---------------------------------------------------------------------------


class TextForIssueTest(TestCase):

    def _dummy(self, **kw):
        class _I:
            pass
        i = _I()
        for k, v in kw.items():
            setattr(i, k, v)
        return i

    def test_omits_empty_fields(self):
        i = self._dummy(root_cause='pool exhausted', recommendation='',
                        description='', component='', issue_type='')
        out = text_for_issue(i)
        self.assertIn('Root cause: pool exhausted', out)
        self.assertNotIn('Recommendation:', out)
        self.assertNotIn('Description:', out)

    def test_truncates_description(self):
        long_desc = 'x' * 1000
        i = self._dummy(root_cause='', recommendation='', description=long_desc,
                        component='', issue_type='')
        out = text_for_issue(i)
        # 500-char cap
        self.assertLessEqual(len(out), 1000)


# ---------------------------------------------------------------------------
# Issue.find_similar
# ---------------------------------------------------------------------------


class FindSimilarTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='SimOrg')
        cls.other_org = Organisations.objects.create(name='OtherSimOrg')
        cls.batch = AIAnalyzedBatch.objects.create(
            batch_id='b_sim', organisation=cls.org,
        )

    def _issue(self, org, embedding=None, status='RESOLVED', fp='fp',
               root_cause='pool exhausted', component='checkout'):
        i = Issue(
            batch=self.batch, organisation=org, severity='HIGH',
            description='boom', component=component, issue_type='CONNECTION_TIMEOUT',
            fingerprint=fp, status=status, root_cause=root_cause,
            recommendation='raise pool size',
        )
        # Save without triggering the embedding signal — we set embedding
        # manually so tests are deterministic.
        i.embedding = embedding
        i.save()
        return i

    def test_no_embedding_returns_empty(self):
        current = self._issue(self.org, embedding=None, status='OPEN', fp='c1')
        self.assertEqual(current.find_similar(), [])

    def test_matches_identical_text(self):
        vec = _hash_embed('pool exhausted checkout')
        # A resolved past issue with the same embedding.
        past = self._issue(self.org, embedding=vec, fp='past1')
        # Current issue, open, same embedding.
        current = self._issue(self.org, embedding=vec, status='OPEN', fp='cur')
        matches = current.find_similar(min_similarity=0.9)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]['issue'].pk, past.pk)
        self.assertAlmostEqual(matches[0]['similarity'], 1.0, places=3)

    def test_cross_org_excluded(self):
        vec = _hash_embed('shared text')
        # Same-embedding issue in ANOTHER org — must not be returned.
        self._issue(self.other_org, embedding=vec, fp='foreign')
        current = self._issue(self.org, embedding=vec, status='OPEN', fp='cur2')
        self.assertEqual(current.find_similar(min_similarity=0.9), [])

    def test_below_threshold_excluded(self):
        # Different-embedding past issue — cosine below threshold.
        past = self._issue(self.org, embedding=_hash_embed('unrelated'), fp='p2')
        current = self._issue(
            self.org, embedding=_hash_embed('nothing alike xyz'),
            status='OPEN', fp='cur3',
        )
        matches = current.find_similar(min_similarity=0.95)
        # Hash embeddings for unrelated text should NOT approach 1.0.
        self.assertEqual(matches, [])

    def test_open_issues_excluded_from_matches(self):
        vec = _hash_embed('same')
        # Another OPEN issue with the same embedding — must be excluded
        # (we only surface RESOLVED precedent).
        other_open = self._issue(self.org, embedding=vec, status='OPEN', fp='p4')
        current = self._issue(self.org, embedding=vec, status='OPEN', fp='cur4')
        self.assertEqual(current.find_similar(), [])

    def test_self_excluded(self):
        vec = _hash_embed('self-match')
        current = self._issue(self.org, embedding=vec, status='RESOLVED', fp='self')
        # Should not return self.
        matches = current.find_similar()
        self.assertNotIn(current.pk, [m['issue'].pk for m in matches])


# ---------------------------------------------------------------------------
# SimilarIssuesView endpoint
# ---------------------------------------------------------------------------


class SimilarIssuesEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='EOrg')
        self.other_org = Organisations.objects.create(name='FOrg')
        self.user = User.objects.create_user(
            username='u', email='u@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='eb', organisation=self.org,
        )
        vec = _hash_embed('shared')
        self.past = Issue(
            batch=self.batch, organisation=self.org, severity='HIGH',
            description='past', component='checkout', issue_type='CONNECTION_TIMEOUT',
            fingerprint='past', status='RESOLVED', root_cause='same', recommendation='fix',
            embedding=vec,
        )
        self.past.save()
        self.current = Issue(
            batch=self.batch, organisation=self.org, severity='HIGH',
            description='current', component='checkout', issue_type='CONNECTION_TIMEOUT',
            fingerprint='current', status='OPEN', root_cause='same',
            embedding=vec,
        )
        self.current.save()
        self.foreign = Issue(
            batch=self.batch, organisation=self.other_org, severity='HIGH',
            description='x', component='c', issue_type='CONNECTION_TIMEOUT',
            fingerprint='foreign', status='OPEN', embedding=vec,
        )
        self.foreign.save()
        self.client = APIClient()

    def _url(self, iid):
        return f'/api/data/issues/{iid}/similar/'

    def test_auth_required(self):
        self.assertIn(self.client.get(self._url(self.current.pk)).status_code, (401, 403))

    def test_returns_similar(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url(self.current.pk))
        self.assertEqual(response.status_code, 200)
        results = response.json()['results']
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.past.pk)
        self.assertGreater(results[0]['similarity'], 0.9)

    def test_cross_org_404(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self._url(self.foreign.pk))
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Post-mortem generator (template path — no AI mock needed)
# ---------------------------------------------------------------------------


class PostmortemTemplateTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.org = Organisations.objects.create(name='PMOrg')
        cls.project = Project.objects.create(organisation=cls.org, name='api-svc')
        cls.batch = AIAnalyzedBatch.objects.create(
            batch_id='pm_batch', organisation=cls.org, project=cls.project,
            environment='production',
            data={'code_changes': [{'sha': 'abcd1234', 'author': 'me',
                                     'message': 'refactor', 'timestamp': '2026-09-04T12:00:00Z'}]},
        )
        Issue.objects.create(
            batch=cls.batch, organisation=cls.org, severity='CRITICAL',
            description='pool exhausted', component='checkout',
            issue_type='CONNECTION_TIMEOUT', fingerprint='pm_top',
            root_cause='DB connection pool exhausted under load',
            recommendation='Increase pool_max to 50',
        )

    @patch('ai_model.postmortem._ai_generate', return_value='')
    def test_falls_back_to_template_on_ai_failure(self, ai_mock):
        from ai_model.postmortem import generate_postmortem_draft
        md = generate_postmortem_draft(self.batch)
        self.assertIn('# Post-mortem:', md)
        self.assertIn('## Summary', md)
        self.assertIn('## Timeline', md)
        self.assertIn('DB connection pool exhausted', md)
        # Deploy info surfaced.
        self.assertIn('abcd1234', md)
        # Placeholder markers present so SRE knows where to edit.
        self.assertIn('[FILL IN', md)

    @patch('ai_model.postmortem._ai_generate', return_value='# Post-mortem: AI wrote this\n\n## Summary\nlong-enough-markdown-response ' * 10)
    def test_uses_ai_output_when_returned(self, ai_mock):
        from ai_model.postmortem import generate_postmortem_draft
        md = generate_postmortem_draft(self.batch)
        self.assertIn('AI wrote this', md)


class PostmortemEndpointTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='PMEOrg')
        self.other_org = Organisations.objects.create(name='ForeignPMOrg')
        self.user = User.objects.create_user(
            username='pm', email='pm@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='pm_end', organisation=self.org, environment='production',
        )
        self.foreign_batch = AIAnalyzedBatch.objects.create(
            batch_id='pm_foreign', organisation=self.other_org, environment='production',
        )
        self.client = APIClient()

    @patch('ai_model.postmortem._ai_generate', return_value='')
    def test_own_batch_returns_markdown(self, _ai_mock):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f'/api/data/batches/{self.batch.batch_id}/postmortem/')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['batch_id'], 'pm_end')
        self.assertIn('# Post-mortem:', body['markdown'])

    @patch('ai_model.postmortem._ai_generate', return_value='')
    def test_cross_org_404(self, _ai_mock):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(f'/api/data/batches/{self.foreign_batch.batch_id}/postmortem/')
        self.assertEqual(response.status_code, 404)
