"""
Elasticsearch Adapter for LogProvider.

Implements the LogProvider ABC using the official elasticsearch-py client.
Wraps existing logic from Utils/elastic_search.py but returns canonical LogEntry objects.
"""
import logging
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any

from django.conf import settings
from elasticsearch import Elasticsearch, helpers, exceptions as es_exceptions

from ..base import LogProvider, LogProviderCapabilities
from ..schemas import LogEntry, LogStream, LogQuery

logger = logging.getLogger(__name__)


class ElasticsearchLogProvider(LogProvider):
    """
    Elasticsearch implementation of the LogProvider interface.
    Handles connection, searching, indexing, and mapping content to canonical LogEntry.
    """

    MAX_RESULTS = 5000

    # Define capabilities
    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=False,
        max_query_window_days=30,
        indexing=True
    )

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.client = self._create_client()
        self.default_index = '_all'
        self.index_patterns = parse_index_patterns(self._config.get('index_pattern'))

    def _create_client(self) -> Elasticsearch:
        """
        Create and configure the Elasticsearch client.

        Prefers per-org config (self._config) from the ObservabilityIntegration model.
        Falls back to global Django settings when per-org values are not set.
        """
        if not self._config:
            raise ValueError("Elasticsearch configuration missing")

        host = self._config.get('host')
        if not host:
             raise ValueError("Elasticsearch host not configured in integration settings")
             
        connection_params = {
            "hosts": [host],
            "request_timeout": self.timeout_seconds,
            "retry_on_timeout": True,
            "max_retries": self.max_retries,
            "verify_certs": self._config.get('verify_certs', True)
        }

        # Auth
        username = self._config.get('username')
        password = self._config.get('password')
        if username and password:
            connection_params["basic_auth"] = (username, password)
            
        # API Key auth (alternative)
        api_key = self._config.get('api_key')
        if api_key:
             connection_params["api_key"] = api_key

        return Elasticsearch(**connection_params)

    def index(self, documents: List[dict], stream: LogStream) -> int:
        """
        Index event documents into Elasticsearch using bulk API.
        
        Routes to index: stream.to_index_name()  →  e.g. "serops-cicd-acme-corp"
        """
        if not documents:
            return 0

        target_index = stream.to_index_name()
        actions = [
            {
                "_index": target_index,
                "_source": doc,
            }
            for doc in documents
        ]

        try:
            success, errors = helpers.bulk(
                self.client,
                actions,
                raise_on_error=False,
                stats_only=True,
            )
            if errors:
                logger.warning(
                    f"ES bulk index: {success} ok, {errors} failed → {target_index}"
                )
            else:
                logger.info(f"ES bulk index: {success} docs → {target_index}")
            return success
        except Exception as e:
            logger.error(f"ES bulk index failed for {target_index}: {e}", exc_info=True)
            return 0

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery (new)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Search logs in Elasticsearch and return canonical LogEntry objects.
        
        Args:
            index: Index pattern or comma-separated list
            query: Elasticsearch query DSL (dict) or LogQuery (agnostic)
            time_range: (start, end) tuple. If provided, adds/merges range filter.
            size: Number of documents to return
            
        Returns:
            List of LogEntry objects
        """
        # Ensure index is not None
        target_index = index if index else self.default_index

        # Translate LogQuery → ES DSL if needed
        if isinstance(query, LogQuery):
            final_query = query.to_es_dsl()
            size = query.max_results
        else:
            # Legacy dict query
            final_query = query.copy() if query else {"query": {"match_all": {}}}
        
        # Apply time range if provided (and not already in LogQuery)
        if time_range and not isinstance(query, LogQuery):
            start_dt, end_dt = time_range
            range_filter = {
                "range": {
                    "@timestamp": {
                        "gte": start_dt.isoformat(),
                        "lte": end_dt.isoformat()
                    }
                }
            }
            
            # Merge into bool query
            if "query" not in final_query:
                final_query["query"] = {"bool": {"must": []}}
            
            if "bool" not in final_query["query"]:
                # Convert top-level query to bool/must
                existing = final_query["query"]
                final_query["query"] = {"bool": {"must": [existing]}}
                
            if "must" not in final_query["query"]["bool"]:
                final_query["query"]["bool"]["must"] = []
                
            # If must is a dict (legacy syntax), convert to list
            if isinstance(final_query["query"]["bool"]["must"], dict):
                final_query["query"]["bool"]["must"] = [final_query["query"]["bool"]["must"]]
                
            final_query["query"]["bool"]["must"].append(range_filter)

    
        # Remove 'size' from body to avoid duplicate with keyword arg
        body_size = final_query.pop('size', None)
        effective_size = size if size is not None else body_size
        effective_size = min(effective_size or self.MAX_RESULTS, self.MAX_RESULTS)

        try:
            response = self.client.search(
                index=target_index,
                body=final_query,
                size=effective_size,
                # One missing pattern (a project with no system-* index,
                # say) must not fail the whole search.
                ignore_unavailable=True,
                allow_no_indices=True,
            )

            hits = response.get('hits', {}).get('hits', [])
            return [LogEntry.from_es_hit(hit) for hit in hits]

        except (es_exceptions.ConnectionError, es_exceptions.ConnectionTimeout) as e:
            logger.error(f"Elasticsearch connection failed: {e}")
            raise
        except es_exceptions.AuthenticationException as e:
            logger.error(f"Elasticsearch authentication failed: {e}")
            raise
        except es_exceptions.AuthorizationException as e:
            logger.error(f"Elasticsearch authorization failed: {e}")
            raise
        except es_exceptions.NotFoundError:
            logger.debug(f"Elasticsearch index not found: {target_index}")
            return []
        except es_exceptions.RequestError as e:
            logger.warning(f"Elasticsearch bad request for {target_index}: {e}")
            return []
        except Exception as e:
            logger.error(f"Elasticsearch search failed: {e}", exc_info=True)
            raise

    def get_indices(self, project) -> List[str]:
        """Indices to search for a project: see :func:`discover_log_indices`."""
        return discover_log_indices(self.client, project, self.index_patterns)

    def health_check(self) -> bool:
        """Check if Elasticsearch is reachable."""
        try:
            return self.client.ping()
        except Exception as e:
            logger.error(f"Elasticsearch health check failed: {e}")
            return False


# Where shippers write by default when nobody chose a name: Elastic Agent
# and OpenTelemetry data streams (logs-*), Filebeat, Logstash.
DEFAULT_LOG_INDEX_PATTERNS = ['logs-*', 'filebeat-*', 'logstash-*']


def parse_index_patterns(value) -> List[str]:
    """The integration's index pattern setting: a comma-separated string or a list."""
    if not value:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(',')
    return [p.strip() for p in items if p and p.strip()]


def discover_log_indices(client, project, configured: List[str]) -> List[str]:
    """Indices (or patterns) to search for ``project``.

    1. The integration's ``index_pattern`` setting, when set: used as is.
    2. Otherwise SerOps' own naming (``application-logs-<project>*``,
       ``serops-*-<project>*``, ``serops-application-<org>*``).
    3. Otherwise the shippers' default patterns that hold any data.

    Records are still filtered by project and environment fields, so a
    broad pattern is safe. Step 3 used to be missing: anyone whose logs
    were in ``logs-*`` or ``filebeat-*`` (our own Elasticsearch guide
    recommends ``logs-*``) had their project skipped without a word.
    """
    if configured:
        return list(configured)
    import re
    raw_name = project.name if hasattr(project, 'name') else str(project)
    clean_name = re.sub(r'[^a-z0-9]+', '-', raw_name.lower().strip()).strip('-')
    patterns = [f"application-logs-{clean_name}*", f"serops-*-{clean_name}*"]
    org_slug = getattr(getattr(project, 'organisation', None), 'slug', '') or ''
    if org_slug:
        patterns.append(f"serops-application-{org_slug}*")

    found = []
    for pattern in patterns:
        try:
            found.extend(i['index'] for i in client.cat.indices(index=pattern, format="json", h="index"))
        except Exception:
            continue
    if found:
        return sorted(set(found))

    defaults = []
    for pattern in DEFAULT_LOG_INDEX_PATTERNS:
        try:
            # count covers data streams too (cat.indices only lists their
            # hidden .ds-* backing indices).
            if client.count(index=pattern, ignore_unavailable=True, allow_no_indices=True).get('count'):
                defaults.append(pattern)
        except Exception as exc:
            logger.debug("Index pattern %s not usable: %s", pattern, exc)
    return defaults
