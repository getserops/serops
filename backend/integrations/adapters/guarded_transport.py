"""Elasticsearch and OpenSearch connections that check the outbound URL
policy before every request, as ``Utils.outbound.GuardedSession`` does for
the adapters built on requests.

The clients used to be checked once, when the adapter was built. Adapters
are cached for the life of the worker (``IntegrationRegistry._cache``), so a
host that resolved to a public address at first use and was then pointed at
``10.0.0.5`` or ``169.254.169.254`` kept receiving searches, index listings
and bulk writes with the integration's credentials.
"""
from functools import lru_cache

from Utils.outbound import check_url


@lru_cache(maxsize=None)
def guarded_es_node_class():
    """An elastic-transport node class (``Elasticsearch(node_class=...)``)."""
    from elastic_transport import Urllib3HttpNode

    class GuardedUrllib3HttpNode(Urllib3HttpNode):
        def perform_request(self, *args, **kwargs):
            check_url(self.base_url)
            return super().perform_request(*args, **kwargs)

    return GuardedUrllib3HttpNode


@lru_cache(maxsize=None)
def guarded_opensearch_connection_class():
    """An opensearch-py connection class (``OpenSearch(connection_class=...)``)."""
    from opensearchpy import Urllib3HttpConnection

    class GuardedUrllib3HttpConnection(Urllib3HttpConnection):
        def perform_request(self, *args, **kwargs):
            check_url(self.host)
            return super().perform_request(*args, **kwargs)

    return GuardedUrllib3HttpConnection
