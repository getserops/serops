"""Elasticsearch and OpenSearch connections that check the outbound URL
policy before every request, as ``Utils.outbound.GuardedSession`` does for
the adapters built on requests.

The clients used to be checked once, when the adapter was built. Adapters
are cached for the life of the worker (``IntegrationRegistry._cache``), so a
host that resolved to a public address at first use and was then pointed at
``10.0.0.5`` or ``169.254.169.254`` kept receiving searches, index listings
and bulk writes with the integration's credentials.
"""
import time
from functools import lru_cache

from Utils import query_trail
from Utils.outbound import check_url


@lru_cache(maxsize=None)
def guarded_es_node_class():
    """An elastic-transport node class (``Elasticsearch(node_class=...)``)."""
    from elastic_transport import Urllib3HttpNode

    class GuardedUrllib3HttpNode(Urllib3HttpNode):
        def perform_request(self, method, target, *args, **kwargs):
            check_url(self.base_url)
            if not query_trail.active():
                return super().perform_request(method, target, *args, **kwargs)
            body = kwargs.get('body', args[0] if args else None)
            started = time.monotonic()
            try:
                response = super().perform_request(method, target, *args, **kwargs)
            except Exception as exc:
                query_trail.record(query_trail.host_of(self.base_url), method, self.base_url + target,
                                   request_body=body, error=exc, started=started)
                raise
            query_trail.record(query_trail.host_of(self.base_url), method, self.base_url + target,
                               request_body=body, status=getattr(response.meta, 'status', None),
                               response_body=response.body, started=started)
            return response

    return GuardedUrllib3HttpNode


@lru_cache(maxsize=None)
def guarded_opensearch_connection_class():
    """An opensearch-py connection class (``OpenSearch(connection_class=...)``)."""
    from opensearchpy import Urllib3HttpConnection

    class GuardedUrllib3HttpConnection(Urllib3HttpConnection):
        def perform_request(self, method, url, params=None, body=None, *args, **kwargs):
            check_url(self.host)
            if not query_trail.active():
                return super().perform_request(method, url, params, body, *args, **kwargs)
            full = self.host + url + (('?' + '&'.join(f'{k}={v}' for k, v in params.items())) if params else '')
            started = time.monotonic()
            try:
                status, headers, data = super().perform_request(method, url, params, body, *args, **kwargs)
            except Exception as exc:
                query_trail.record(query_trail.host_of(self.host), method, full, request_body=body,
                                   error=exc, started=started)
                raise
            query_trail.record(query_trail.host_of(self.host), method, full, request_body=body,
                               status=status, response_body=data, started=started)
            return status, headers, data

    return GuardedUrllib3HttpConnection
