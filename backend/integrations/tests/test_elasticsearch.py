
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from django.test import SimpleTestCase, override_settings
from elasticsearch import exceptions as es_exceptions

from integrations.adapters.elasticsearch import ElasticsearchLogProvider
from integrations.schemas import LogEntry


class TestElasticsearchLogProvider(SimpleTestCase):
    
    @patch('integrations.adapters.elasticsearch.Elasticsearch')
    def setUp(self, mock_es_class):
        self.mock_client = MagicMock()
        mock_es_class.return_value = self.mock_client
        self.provider = ElasticsearchLogProvider(config={'host': 'http://localhost:9200'})

    def test_health_check_success(self):
        self.mock_client.ping.return_value = True
        self.assertTrue(self.provider.health_check())

    def test_health_check_failure(self):
        self.mock_client.ping.return_value = False
        self.assertFalse(self.provider.health_check())
        
    def test_health_check_exception(self):
        self.mock_client.ping.side_effect = Exception("Connection error")
        self.assertFalse(self.provider.health_check())

    def test_search_basic(self):
        # Mock response
        mock_hits = [
            {
                "_id": "1",
                "_source": {
                    "@timestamp": "2023-01-01T12:00:00Z",
                    "message": "test log",
                    "level": "INFO",
                    "service": "api",
                    "host": "server1"
                }
            }
        ]
        self.mock_client.search.return_value = {"hits": {"hits": mock_hits}}

        entries = self.provider.search("test-index", {"query": {"match_all": {}}})
        
        self.assertEqual(len(entries), 1)
        self.assertIsInstance(entries[0], LogEntry)
        self.assertEqual(entries[0].message, "test log")
        self.assertEqual(entries[0].raw_id, "1")
        
        # Verify call — size is capped at MAX_RESULTS (5000)
        self.mock_client.search.assert_called_with(
            index="test-index",
            body={"query": {"match_all": {}}},
            size=5000,
        )

    def test_search_with_time_range(self):
        self.mock_client.search.return_value = {"hits": {"hits": []}}
        
        start = datetime(2023, 1, 1, 10, 0, 0)
        end = datetime(2023, 1, 1, 11, 0, 0)
        
        self.provider.search("test-index", {"query": {"match_all": {}}}, time_range=(start, end))
        
        # Verify query structure
        call_args = self.mock_client.search.call_args
        body = call_args.kwargs['body']
        
        # Check if match_all is preserved inside bool/must
        self.assertIn("bool", body["query"])
        self.assertIn("must", body["query"]["bool"])
        
        # Check for range filter
        must_clauses = body["query"]["bool"]["must"]
        range_clause = next((c for c in must_clauses if "range" in c), None)
        self.assertIsNotNone(range_clause)
        self.assertEqual(range_clause["range"]["@timestamp"]["gte"], start.isoformat())
        self.assertEqual(range_clause["range"]["@timestamp"]["lte"], end.isoformat())

    def test_get_indices(self):
        # Mock cat.indices — returns results for first pattern, NotFoundError for second
        def cat_indices_side_effect(index=None, **kwargs):
            if index.startswith('application-logs'):
                return [
                    {"index": "application-logs-demo-2023"},
                    {"index": "application-logs-demo-error"},
                ]
            raise es_exceptions.NotFoundError(
                    'index_not_found_exception', MagicMock(), 'index_not_found'
                )

        self.mock_client.cat.indices.side_effect = cat_indices_side_effect

        class MockProject:
            name = "Demo Project"

        indices = self.provider.get_indices(MockProject())

        self.assertEqual(len(indices), 2)
        self.assertIn("application-logs-demo-2023", indices)
        # cat.indices called twice (one per pattern)
        self.assertEqual(self.mock_client.cat.indices.call_count, 2)

    def test_get_indices_multiple_patterns(self):
        """get_indices should search both application-logs-* and serops-*-* patterns."""
        def cat_indices_side_effect(index=None, **kwargs):
            if 'application-logs' in index:
                return [{"index": "application-logs-myapp-2024"}]
            if 'serops-' in index:
                return [{"index": "serops-cicd-myapp-2024"}]
            return []

        self.mock_client.cat.indices.side_effect = cat_indices_side_effect

        class MockProject:
            name = "MyApp"

        indices = self.provider.get_indices(MockProject())

        self.assertEqual(len(indices), 2)
        self.assertIn("application-logs-myapp-2024", indices)
        self.assertIn("serops-cicd-myapp-2024", indices)

    def test_search_caps_size_at_max(self):
        """Size parameter should be capped at MAX_RESULTS."""
        self.mock_client.search.return_value = {"hits": {"hits": []}}

        self.provider.search("test-index", {"query": {"match_all": {}}}, size=99999)

        call_args = self.mock_client.search.call_args
        self.assertEqual(call_args.kwargs['size'], ElasticsearchLogProvider.MAX_RESULTS)

    def test_search_connection_error_raises(self):
        """ConnectionError should propagate, not be silently caught."""
        self.mock_client.search.side_effect = es_exceptions.ConnectionError(
            'N/A', 'Connection refused'
        )

        with self.assertRaises(es_exceptions.ConnectionError):
            self.provider.search("test-index", {"query": {"match_all": {}}})

    def test_search_auth_error_raises(self):
        """AuthenticationException should propagate."""
        self.mock_client.search.side_effect = es_exceptions.AuthenticationException(
            'security_exception', MagicMock(), 'Unauthorized'
        )

        with self.assertRaises(es_exceptions.AuthenticationException):
            self.provider.search("test-index", {"query": {"match_all": {}}})

    def test_search_not_found_returns_empty(self):
        """NotFoundError (missing index) should return empty list."""
        self.mock_client.search.side_effect = es_exceptions.NotFoundError(
            'index_not_found_exception', MagicMock(), 'index_not_found'
        )

        result = self.provider.search("missing-index", {"query": {"match_all": {}}})
        self.assertEqual(result, [])

    def test_search_bad_request_returns_empty(self):
        """RequestError (bad query) should return empty list."""
        self.mock_client.search.side_effect = es_exceptions.RequestError(
            'parsing_exception', MagicMock(), 'bad_request'
        )

        result = self.provider.search("test-index", {"query": {"bad": "query"}})
        self.assertEqual(result, [])

    @patch('integrations.adapters.elasticsearch.Elasticsearch')
    def test_verify_certs_configurable(self, mock_es_class):
        """verify_certs should default to True and be configurable."""
        mock_es_class.return_value = MagicMock()

        # Default: verify_certs=True
        provider = ElasticsearchLogProvider(config={'host': 'http://localhost:9200'})
        call_kwargs = mock_es_class.call_args.kwargs
        self.assertTrue(call_kwargs['verify_certs'])

        # Explicit: verify_certs=False
        provider = ElasticsearchLogProvider(
            config={'host': 'http://localhost:9200', 'verify_certs': False}
        )
        call_kwargs = mock_es_class.call_args.kwargs
        self.assertFalse(call_kwargs['verify_certs'])

