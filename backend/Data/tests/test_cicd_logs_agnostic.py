"""
Tests for provider-agnostic CI/CD log fetching in batch creation.

Verifies that CI/CD logs are fetched through the LogProvider abstraction
using LogQuery, LogStream routing, and structured document format.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from integrations.schemas import LogEntry, LogQuery, LogStream


class TestCicdLogStreamRouting(SimpleTestCase):
    """Test that CI/CD log streams route to correct index/labels."""

    def test_index_name_uses_org_slug(self):
        stream = LogStream(category='cicd', org_slug='acme', project='demo')
        self.assertEqual(stream.to_index_name(), 'serops-cicd-acme')

    def test_loki_labels_include_category(self):
        stream = LogStream(
            category='cicd', org_slug='acme',
            project='demo', environment='production',
        )
        labels = stream.to_loki_labels()
        self.assertEqual(labels['category'], 'cicd')
        self.assertEqual(labels['organisation_name'], 'acme')
        self.assertEqual(labels['project_name'], 'demo')
        self.assertEqual(labels['environment'], 'production')

    def test_datadog_tags(self):
        stream = LogStream(category='cicd', org_slug='acme', project='demo')
        tags = stream.to_datadog_tags()
        self.assertIn('source:serops', tags)
        self.assertIn('category:cicd', tags)
        self.assertIn('organisation_name:acme', tags)

    def test_cloudwatch_log_group(self):
        stream = LogStream(category='cicd', org_slug='acme')
        self.assertEqual(stream.to_cloudwatch_log_group(), '/serops/cicd/acme')


class TestCicdLogQueryTranslation(SimpleTestCase):
    """Test that LogQuery correctly translates CI/CD filters."""

    def test_es_dsl_translation(self):
        query = LogQuery(
            time_range=(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0)),
            environment='production',
            category='cicd',
            project='demo',
            max_results=100,
        )
        dsl = query.to_es_dsl()

        self.assertIn('query', dsl)
        self.assertEqual(dsl['size'], 100)
        filters = dsl['query']['bool']['filter']

        # Environment + project are now emitted as bool.should over aliases
        # (Datadog USM `env`, OpenTelemetry `deployment.environment`, etc.).
        # Flatten term-clauses across both direct and bool.should shapes.
        def flat_terms(clauses):
            for c in clauses:
                if 'term' in c:
                    yield c['term']
                elif 'bool' in c and 'should' in c['bool']:
                    for s in c['bool']['should']:
                        if 'term' in s:
                            yield s['term']

        terms = list(flat_terms(filters))

        # Environment=production must appear (under `environment` canonical key)
        self.assertTrue(
            any(t.get('environment') == 'production' for t in terms),
            "environment=production should be in the ES filters",
        )

        # Category has no ALIASES (no alternative field names), but it is
        # still wrapped in a bool.should so the E9-1 `.keyword` variant can
        # sit beside the plain field — an analysed field never matches a term
        # query, so both forms are queried. This assertion used to look for a
        # top-level {'term': {'category': ...}} and so failed on correct
        # output; `flat_terms` above already walks both shapes.
        self.assertTrue(
            any(t.get('category') == 'cicd' for t in terms),
            "category=cicd should be in the ES filters",
        )
        self.assertTrue(
            any(t.get('category.keyword') == 'cicd' for t in terms),
            "category.keyword=cicd should be queried too, for "
            "dynamically-mapped indices where `category` is analysed",
        )

        # Alias smoke: the ENV bool.should should include `env` as an alias
        env_clause = next(
            (f for f in filters if 'bool' in f and any(
                'environment' in s.get('term', {}) for s in f['bool'].get('should', [])
            )),
            None,
        )
        self.assertIsNotNone(env_clause, "environment filter should be a bool.should over aliases")
        env_aliases_used = {
            list(s['term'].keys())[0] for s in env_clause['bool']['should'] if 'term' in s
        }
        self.assertIn('env', env_aliases_used, "Datadog USM `env` should be a queried alias")

    def test_logql_translation(self):
        query = LogQuery(environment='production', category='cicd', project='demo')
        logql = query.to_logql()
        self.assertIn('environment="production"', logql)
        self.assertIn('category="cicd"', logql)
        self.assertIn('project_name="demo"', logql)

    def test_datadog_query_translation(self):
        query = LogQuery(environment='staging', category='cicd')
        dd = query.to_datadog_query()
        self.assertIn('@environment:staging', dd)
        self.assertIn('@category:cicd', dd)


class TestCicdLogDeduplication(SimpleTestCase):
    """Test CI/CD log dedup logic with nested doc format."""

    def _make_log_entry(self, labels, message='', timestamp=None):
        return LogEntry(
            timestamp=timestamp or datetime(2026, 1, 1, 10, 0),
            message=message,
            labels=labels,
        )

    def test_dedup_prefers_record_with_trace(self):
        """Duplicate pipeline/job entries should keep the one WITH trace."""
        entries = [
            self._make_log_entry({
                'pipeline': {'id': '100', 'ref': 'main', 'status': 'failed'},
                'job': {'id': '1', 'name': 'test', 'status': 'failed', 'duration_seconds': 30},
                'serops_meta': {'environment': 'production', 'service_name': 'api'},
            }),
            self._make_log_entry({
                'pipeline': {'id': '100', 'ref': 'main', 'status': 'failed'},
                'job': {'id': '1', 'name': 'test', 'status': 'failed', 'duration_seconds': 30},
                'trace': 'Error: test failed\nline 2',
                'serops_meta': {'environment': 'production', 'service_name': 'api'},
            }),
        ]

        seen_jobs = {}
        for entry in entries:
            source = entry.labels
            p_id = source.get('pipeline', {}).get('id')
            j_name = source.get('job', {}).get('name')
            raw_trace = source.get('trace', '')

            key = (p_id, j_name)
            if key in seen_jobs and seen_jobs[key].get('trace'):
                continue
            if key not in seen_jobs or raw_trace:
                seen_jobs[key] = {'pipeline_id': p_id, 'job_name': j_name, 'trace': raw_trace}

        self.assertEqual(len(seen_jobs), 1)
        self.assertIn('Error: test failed', seen_jobs[('100', 'test')]['trace'])

    def test_dedup_different_jobs_kept_separate(self):
        """Different pipeline/job combinations should not be deduped."""
        entries = [
            self._make_log_entry({
                'pipeline': {'id': '300'},
                'job': {'name': 'build'},
            }),
            self._make_log_entry({
                'pipeline': {'id': '300'},
                'job': {'name': 'test'},
            }),
            self._make_log_entry({
                'pipeline': {'id': '301'},
                'job': {'name': 'build'},
            }),
        ]

        seen_jobs = {}
        for entry in entries:
            source = entry.labels
            p_id = source.get('pipeline', {}).get('id')
            j_name = source.get('job', {}).get('name')
            raw_trace = source.get('trace', '')

            key = (p_id, j_name)
            if key in seen_jobs and seen_jobs[key].get('trace'):
                continue
            if key not in seen_jobs or raw_trace:
                seen_jobs[key] = {'pipeline_id': p_id, 'job_name': j_name, 'trace': raw_trace}

        self.assertEqual(len(seen_jobs), 3)


class TestCicdEventDocTimestamp(SimpleTestCase):
    """Test that CI/CD event docs include @timestamp for LogQuery compat."""

    @patch('providers.utils.datetime')
    def test_event_doc_has_at_timestamp(self, mock_dt):
        from providers.utils import _build_cicd_event_doc

        fake_now = datetime(2026, 2, 16, 12, 0, 0)
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        mock_project = Mock(id=1)
        mock_project.name = 'demo'
        doc = _build_cicd_event_doc(
            org=Mock(id=1, slug='acme'),
            project=mock_project,
            service_name='api',
            environment='production',
            pipeline_id='100',
            pipeline_ref='main',
            pipeline_status='failed',
            pipeline_url='',
            job_id='1',
            job_name='test',
            job_stage='test',
            job_status='failed',
            job_duration=30,
        )

        self.assertIn('@timestamp', doc)
        self.assertIn('timestamp', doc)
        # Both should be ISO format strings
        self.assertIsInstance(doc['@timestamp'], str)
        self.assertIsInstance(doc['timestamp'], str)

        # Flat canonical fields for unified querying
        self.assertEqual(doc['organisation_name'], 'acme')
        self.assertEqual(doc['project_name'], 'demo')
        self.assertEqual(doc['service_name'], 'api')
        self.assertEqual(doc['environment'], 'production')
        self.assertEqual(doc['log_level'], 'ERROR')  # failed job → ERROR
