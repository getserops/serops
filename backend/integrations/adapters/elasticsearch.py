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
        """
        Get available indices for a project.

        Searches multiple naming conventions:
        - Legacy: application-logs-{project_name}*
        - Per-project: serops-*-{project_name}*
        - Per-org: serops-application-{org_slug}* (shared index, field-level isolation)
        """
        try:
            # Replicate sanitize_project_name logic from legacy code
            raw_name = project.name if hasattr(project, 'name') else str(project)
            clean_name = raw_name.lower().strip()
            # Basic sanitization - should ideally match `Utils.elastic_search.sanitize_project_name`
            import re
            clean_name = re.sub(r'[^a-z0-9]+', '-', clean_name).strip('-')

            # Search both legacy and new index patterns
            patterns = [
                f"application-logs-{clean_name}*",
                f"serops-*-{clean_name}*",
            ]

            # Also search org-scoped index (serops-application-{org_slug})
            if hasattr(project, 'organisation') and project.organisation:
                org_slug = getattr(project.organisation, 'slug', '')
                if org_slug:
                    patterns.append(f"serops-application-{org_slug}*")

            found = []
            for pattern in patterns:
                try:
                    indices = self.client.cat.indices(index=pattern, format="json", h="index")
                    found.extend(i['index'] for i in indices)
                except es_exceptions.NotFoundError:
                    continue
            return sorted(set(found))

        except Exception as e:
            logger.warning(f"Failed to discover indices for project {project}: {e}")
            return []

    def health_check(self) -> bool:
        """Check if Elasticsearch is reachable."""
        try:
            return self.client.ping()
        except Exception as e:
            logger.error(f"Elasticsearch health check failed: {e}")
            return False

