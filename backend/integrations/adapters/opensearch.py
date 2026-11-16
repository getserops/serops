"""
OpenSearch Adapter for LogProvider.

Implements the LogProvider ABC using the opensearch-py client.
API-compatible with Elasticsearch; reuses LogEntry.from_es_hit() for mapping.
"""
import logging
import re
from datetime import datetime
from typing import List, Tuple, Optional

from django.conf import settings

from integrations.base import LogProvider, LogProviderCapabilities, LogSearchError
from integrations.adapters.elasticsearch import _note_es_partial, discover_log_indices, parse_index_patterns
from integrations.schemas import LogEntry, LogStream, LogQuery

logger = logging.getLogger(__name__)


def _verify_certs(config: dict) -> bool:
    """TLS verification is on unless the integration turns it off
    (``verify_certs: false``; "false"/"0"/"no" from the API count too).
    It used to default to off, so a man in the middle saw the password."""
    value = config.get("verify_certs", True)
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _get_opensearch_client(config: dict):
    """
    Create an OpenSearch client.
    Falls back to elasticsearch-py if opensearch-py is not installed,
    since the wire protocol is compatible for basic operations.
    """
    # Checked again here, not only when saved: DNS can change after
    # (security review 2026-11, finding 3). The client does not follow
    # redirects.
    from Utils.outbound import check_url
    from integrations.adapters.guarded_transport import (
        guarded_es_node_class, guarded_opensearch_connection_class,
    )
    host = str(config.get("host", "https://localhost:9200"))
    check_url(host if '://' in host else f'http://{host}')
    try:
        from opensearchpy import OpenSearch
        connection_params = {
            "hosts": [config.get("host", "https://localhost:9200")],
            "timeout": config.get("timeout_seconds", 30),
            "max_retries": config.get("max_retries", 3),
            "retry_on_timeout": True,
            "verify_certs": _verify_certs(config),
            # The outbound policy before every request: the adapter is
            # cached and DNS can change after this first check.
            "connection_class": guarded_opensearch_connection_class(),
        }
        username = config.get("username")
        password = config.get("password")
        if username and password:
            connection_params["http_auth"] = (username, password)
        return OpenSearch(**connection_params)
    except ImportError:
        logger.warning(
            "opensearch-py not installed; falling back to elasticsearch-py. "
            "Install opensearch-py for full OpenSearch compatibility."
        )
        from elasticsearch import Elasticsearch
        connection_params = {
            "hosts": [config.get("host", "https://localhost:9200")],
            "request_timeout": config.get("timeout_seconds", 30),
            "max_retries": config.get("max_retries", 3),
            "retry_on_timeout": True,
            "verify_certs": _verify_certs(config),
            "node_class": guarded_es_node_class(),
        }
        username = config.get("username")
        password = config.get("password")
        if username and password:
            connection_params["basic_auth"] = (username, password)
        return Elasticsearch(**connection_params)


class OpenSearchLogProvider(LogProvider):
    """
    OpenSearch implementation of the LogProvider interface.

    Nearly identical to ElasticsearchLogProvider since OpenSearch
    is a fork of Elasticsearch 7.x. Key differences:
      - Uses opensearch-py client (http_auth instead of basic_auth)
      - Compatible hit format — reuses LogEntry.from_es_hit()
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=False,
        max_query_window_days=30,
        indexing=True,
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        effective_config = self._config.copy()
        # Pull host from Django settings if not in adapter config
        if not effective_config.get("host"):
            os_settings = getattr(settings, "OPENSEARCH", {})
            if os_settings.get("HOST"):
                effective_config["host"] = os_settings["HOST"]
                effective_config.setdefault("username", os_settings.get("USERNAME", ""))
                effective_config.setdefault("password", os_settings.get("PASSWORD", ""))
        self.client = _get_opensearch_client(effective_config)
        self.default_index = effective_config.get("default_index", "_all")
        self.index_patterns = parse_index_patterns(effective_config.get("index_pattern"))

    # ------------------------------------------------------------------
    # LogProvider ABC
    # ------------------------------------------------------------------

    def index(self, documents: list, stream: LogStream) -> int:
        """
        Index event documents into OpenSearch using bulk API.
        Same wire protocol as Elasticsearch.
        """
        if not documents:
            return 0

        target_index = stream.to_index_name()

        # Build bulk body (NDJSON format)
        bulk_body = ""
        for doc in documents:
            import json
            bulk_body += json.dumps({"index": {"_index": target_index}}) + "\n"
            bulk_body += json.dumps(doc) + "\n"

        try:
            response = self.client.bulk(body=bulk_body)
            errors = response.get("errors", False)
            items = response.get("items", [])
            success_count = sum(
                1 for item in items
                if item.get("index", {}).get("status", 500) < 300
            )
            if errors:
                logger.warning(
                    "OpenSearch bulk index: %d ok, %d failed → %s",
                    success_count, len(items) - success_count, target_index,
                )
            else:
                logger.info("OpenSearch bulk index: %d docs → %s", success_count, target_index)
            return success_count
        except Exception as exc:
            logger.error("OpenSearch bulk index failed for %s: %s", target_index, exc, exc_info=True)
            return 0

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery (new)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Search logs in OpenSearch and return canonical LogEntry objects.
        Query format is identical to Elasticsearch DSL.
        """
        target_index = index if index else self.default_index

        # Translate LogQuery → ES DSL if needed
        if isinstance(query, LogQuery):
            final_query = query.to_es_dsl()
            size = query.max_results
        else:
            final_query = query.copy() if query else {"query": {"match_all": {}}}

        if time_range and not isinstance(query, LogQuery):
            start_dt, end_dt = time_range
            range_filter = {
                "range": {
                    "@timestamp": {
                        "gte": start_dt.isoformat(),
                        "lte": end_dt.isoformat(),
                    }
                }
            }
            if "query" not in final_query:
                final_query["query"] = {"bool": {"must": []}}
            if "bool" not in final_query["query"]:
                existing = final_query["query"]
                final_query["query"] = {"bool": {"must": [existing]}}
            if "must" not in final_query["query"]["bool"]:
                final_query["query"]["bool"]["must"] = []
            must = final_query["query"]["bool"]["must"]
            if isinstance(must, dict):
                final_query["query"]["bool"]["must"] = [must]
            final_query["query"]["bool"]["must"].append(range_filter)

        try:
            response = self.client.search(
                index=target_index,
                body=final_query,
                size=size,
                ignore_unavailable=True,
                allow_no_indices=True,
            )
        except Exception as exc:
            # A missing index or pattern is "no logs"; every other failure
            # (connection, auth, a rejected query) must not read as a quiet
            # window (phase 3 review, LG1).
            if type(exc).__name__ == 'NotFoundError':
                logger.debug("OpenSearch index not found: %s", target_index)
                return []
            logger.error("OpenSearch search failed: %s", exc, exc_info=True)
            status = getattr(exc, 'status_code', None)
            raise LogSearchError(
                f'OpenSearch refused the query ({f"HTTP {status}" if isinstance(status, int) else type(exc).__name__})'
            ) from exc
        _note_es_partial(self, response)
        hits = response.get("hits", {}).get("hits", [])
        return [LogEntry.from_es_hit(hit) for hit in hits]

    def get_indices(self, project) -> List[str]:
        """Indices to search for a project (same rules as Elasticsearch)."""
        return discover_log_indices(self.client, project, self.index_patterns)

    def health_check(self) -> bool:
        """Check if OpenSearch cluster is reachable."""
        try:
            health = self.client.cluster.health()
            return health.get("status") in ("green", "yellow")
        except Exception as exc:
            logger.error("OpenSearch health check failed: %s", exc)
            return False
