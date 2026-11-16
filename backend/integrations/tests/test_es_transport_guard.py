"""Elasticsearch and OpenSearch: the outbound policy on every request, and
TLS verified by default on OpenSearch (phase 3 review, LG15 and LG9)."""
from unittest.mock import patch

from django.test import SimpleTestCase

from Utils.outbound import BlockedOutboundURL
from integrations.adapters.guarded_transport import (
    guarded_es_node_class, guarded_opensearch_connection_class,
)


class GuardedTransportTest(SimpleTestCase):
    """The adapters are cached for the life of the worker, so a host that
    passed the check at first use and was later pointed at a private
    address kept receiving requests. Each request is now checked."""

    def test_an_es_request_to_a_host_now_refused_is_not_sent(self):
        from elastic_transport import NodeConfig
        node = guarded_es_node_class()(NodeConfig('https', 'logs.example.com', 443))
        with patch('integrations.adapters.guarded_transport.check_url',
                   side_effect=BlockedOutboundURL('resolves to 10.0.0.5')) as check, \
                patch('elastic_transport.Urllib3HttpNode.perform_request') as sent:
            with self.assertRaises(BlockedOutboundURL):
                node.perform_request('GET', '/_search')
        check.assert_called_once_with('https://logs.example.com:443')
        sent.assert_not_called()

    def test_an_opensearch_request_to_a_host_now_refused_is_not_sent(self):
        conn = guarded_opensearch_connection_class()(host='logs.example.com', port=9200, use_ssl=True)
        with patch('integrations.adapters.guarded_transport.check_url',
                   side_effect=BlockedOutboundURL('resolves to 169.254.169.254')), \
                patch('opensearchpy.Urllib3HttpConnection.perform_request') as sent:
            with self.assertRaises(BlockedOutboundURL):
                conn.perform_request('GET', '/_search')
        sent.assert_not_called()

    def test_an_allowed_request_goes_through(self):
        from elastic_transport import NodeConfig
        node = guarded_es_node_class()(NodeConfig('https', 'logs.example.com', 443))
        with patch('integrations.adapters.guarded_transport.check_url'), \
                patch('elastic_transport.Urllib3HttpNode.perform_request', return_value='ok') as sent:
            self.assertEqual(node.perform_request('GET', '/'), 'ok')
        sent.assert_called_once()

    @patch('Utils.outbound.check_url')
    def test_both_clients_are_built_with_the_guarded_transport(self, _check):
        from integrations.adapters.opensearch import _get_opensearch_client
        with patch('opensearchpy.OpenSearch') as client:
            _get_opensearch_client({'host': 'https://logs.example.com:9200'})
        self.assertIs(client.call_args.kwargs['connection_class'], guarded_opensearch_connection_class())

        from integrations.adapters.elasticsearch import ElasticsearchLogProvider
        with patch('integrations.adapters.elasticsearch.Elasticsearch') as client:
            ElasticsearchLogProvider({'host': 'https://logs.example.com:9200'})
        self.assertIs(client.call_args.kwargs['node_class'], guarded_es_node_class())


class OpenSearchTLSTest(SimpleTestCase):

    def _kwargs(self, **config):
        from integrations.adapters.opensearch import _get_opensearch_client
        with patch('Utils.outbound.check_url'), patch('opensearchpy.OpenSearch') as client:
            _get_opensearch_client({'host': 'https://logs.example.com:9200', **config})
        return client.call_args.kwargs

    def test_certificates_are_verified_by_default(self):
        self.assertTrue(self._kwargs()['verify_certs'])

    def test_verification_can_be_turned_off_explicitly(self):
        self.assertFalse(self._kwargs(verify_certs=False)['verify_certs'])
        self.assertFalse(self._kwargs(verify_certs='false')['verify_certs'])
        self.assertTrue(self._kwargs(verify_certs='true')['verify_certs'])
