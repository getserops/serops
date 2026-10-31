"""
AWS CloudWatch Logs Adapter for LogProvider.

Implements the LogProvider ABC using boto3 CloudWatch Logs client.
Uses CloudWatch Logs Insights for querying (async start_query → poll get_query_results).
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.field_aliases import first_present
from integrations.schemas import (
    MESSAGE_FIELDS, LogEntry, LogStream, LogQuery, _parse_timestamp, _detect_level, level_of,
)

logger = logging.getLogger(__name__)


def _get_boto3_client(service: str, config: dict):
    """Create a boto3 client from the integration's own access key.

    The access key ID is the integration's ``username`` and the secret
    access key its ``password``, which is encrypted at rest. Both are
    required. Without them boto3 would fall back to its default credential
    chain — environment variables, the instance profile, an EKS pod role —
    and a multi-tenant SerOps process must never lend one organisation the
    host's own AWS identity. The GCP and Azure adapters refuse ambient
    credentials for the same reason.
    """
    access_key = config.get("username")
    secret_key = config.get("password")
    if not (access_key and secret_key):
        raise ValueError(
            "AWS CloudWatch requires an access key ID and a secret access "
            "key; SerOps never uses the server's own AWS credentials"
        )
    try:
        import boto3
    except ImportError:
        raise ImportError(
            "boto3 is required for CloudWatch integration. "
            "Install it with: pip install boto3"
        )
    return boto3.client(
        service_name=service,
        region_name=config.get("aws_region") or "us-east-1",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


class CloudWatchLogProvider(LogProvider):
    """
    AWS CloudWatch Logs adapter.

    Uses CloudWatch Logs Insights for powerful query capabilities.
    Queries are asynchronous: start_query → poll get_query_results.
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=False,
        max_query_window_days=30,
        indexing=True,
    )

    # Polling config for Logs Insights
    POLL_INTERVAL = 0.5  # seconds between polls
    MAX_POLL_ATTEMPTS = 60  # max ~30 seconds wait

    def __init__(self, config: dict = None):
        super().__init__(config)
        self.client = _get_boto3_client("logs", self._config)
        self.default_log_group = self._config.get(
            "default_log_group", "/aws/application"
        )
        # Integration setting: log groups to search (comma-separated or a list).
        groups = self._config.get("log_groups") or []
        if isinstance(groups, str):
            groups = groups.split(",")
        self.log_groups = [g.strip() for g in groups if g and g.strip()]

    def index(self, documents: list, stream: LogStream) -> int:
        """
        Write event documents to CloudWatch Logs via put_log_events.
        Log group is derived from LogStream.
        """
        if not documents:
            return 0

        import json

        log_group = stream.to_cloudwatch_log_group()
        log_stream = f"{stream.project or 'default'}-{stream.service or 'events'}"

        # Ensure log group and stream exist
        try:
            self.client.create_log_group(logGroupName=log_group)
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception as exc:
            logger.warning("Could not create log group %s: %s", log_group, exc)

        try:
            self.client.create_log_stream(
                logGroupName=log_group, logStreamName=log_stream
            )
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception as exc:
            logger.warning("Could not create log stream %s: %s", log_stream, exc)

        events = []
        for doc in documents:
            ts_ms = int(datetime.utcnow().timestamp() * 1000)
            if "timestamp" in doc:
                try:
                    dt = datetime.fromisoformat(doc["timestamp"].replace("Z", "+00:00"))
                    ts_ms = int(dt.timestamp() * 1000)
                except (ValueError, AttributeError):
                    pass
            events.append({"timestamp": ts_ms, "message": json.dumps(doc)})

        try:
            self.client.put_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                logEvents=events,
            )
            logger.info(
                "CloudWatch index: %d events → %s/%s",
                len(documents), log_group, log_stream,
            )
            return len(documents)
        except Exception as exc:
            logger.error("CloudWatch put_log_events failed: %s", exc, exc_info=True)
            return 0

    def health_check(self) -> bool:
        """Validate credentials by listing log groups."""
        try:
            self.client.describe_log_groups(limit=1)
            return True
        except Exception as exc:
            logger.error("CloudWatch Logs health check failed: %s", exc)
            return False

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery (new)
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 10000,
    ) -> List[LogEntry]:
        """
        Run a CloudWatch Logs Insights query.
        Accepts both legacy dict queries and LogQuery DTOs.
        """
        # The scheduler passes every discovered group joined by commas;
        # Insights takes them as a list (at most 50 per query).
        log_groups = [g.strip() for g in (index or self.default_log_group).split(",") if g.strip()]
        log_groups = log_groups[:50]
        log_group = log_groups[0] if log_groups else self.default_log_group

        # Translate LogQuery → Insights query if needed
        if isinstance(query, LogQuery):
            insights_query = query.to_cloudwatch_insights()
            size = query.max_results
            if not time_range and query.time_range:
                time_range = query.time_range
        else:
            insights_query = self._build_query(query)

        # Time range defaults to last 1 hour
        if time_range:
            start_dt, end_dt = time_range
        else:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(hours=1)

        try:
            response = self.client.start_query(
                logGroupNames=log_groups,
                startTime=int(start_dt.timestamp()),
                endTime=int(end_dt.timestamp()),
                queryString=insights_query,
                limit=min(size, 10000),  # CW max is 10000
            )
            query_id = response["queryId"]
            return self._poll_results(query_id, log_group)

        except Exception as exc:
            logger.error("CloudWatch Logs search failed: %s", exc)
            return []

    def get_indices(self, project) -> List[str]:
        """Log groups to search for a project.

        The integration's ``log_groups`` setting when set; otherwise groups
        whose name starts with ``/aws/<project>`` or contains the project
        name (``/ecs/shop-api``, ``/serops/application/shop``, ...).
        Records are still filtered by project and environment fields.
        """
        if self.log_groups:
            return list(self.log_groups)
        raw_name = project.name if hasattr(project, "name") else str(project)
        name = raw_name.lower().strip()
        found = []
        for kwargs in ({"logGroupNamePrefix": f"/aws/{name}"}, {"logGroupNamePattern": name}):
            try:
                result = self.client.describe_log_groups(limit=50, **kwargs)
            except Exception as exc:
                logger.warning("CloudWatch describe_log_groups %s failed: %s", kwargs, exc)
                continue
            found += [g["logGroupName"] for g in result.get("logGroups", [])
                      if g["logGroupName"] not in found]
        return found[:50]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _poll_results(
        self, query_id: str, log_group: str
    ) -> List[LogEntry]:
        """Poll for Logs Insights query results until complete."""
        for _ in range(self.MAX_POLL_ATTEMPTS):
            result = self.client.get_query_results(queryId=query_id)
            status = result.get("status")

            if status == "Complete":
                return self._parse_results(result.get("results", []), log_group)
            if status in ("Failed", "Cancelled", "Timeout"):
                logger.warning("CloudWatch query %s ended with status: %s", query_id, status)
                return []

            time.sleep(self.POLL_INTERVAL)

        logger.warning("CloudWatch query %s timed out after polling", query_id)
        return []

    @staticmethod
    def _build_query(query: dict) -> str:
        """Build a Logs Insights query string."""
        # Raw override
        if query.get("insights_query"):
            return query["insights_query"]

        # Build from generic query dict
        parts = ["fields @timestamp, @message, @logStream"]

        match_phrase = query.get("match_phrase", {})
        text = match_phrase.get("message", "")
        if text:
            escaped = text.replace("'", "\\'")
            parts.append(f"| filter @message like '{escaped}'")

        level = query.get("level")
        if level:
            parts.append(f"| filter @message like /(?i){level}/")

        parts.append("| sort @timestamp desc")
        return "\n".join(parts)

    @staticmethod
    def _parse_results(
        results: list, log_group: str
    ) -> List[LogEntry]:
        """
        Parse CloudWatch Logs Insights results into LogEntry objects.

        Each result is a list of dicts: [{"field": "@timestamp", "value": "..."}, ...]
        """
        entries: List[LogEntry] = []
        for row in results:
            fields = {item["field"]: item["value"] for item in row}
            message = fields.get("@message", "")
            log_stream = fields.get("@logStream", "")
            group = fields.get("@log", "").split(":", 1)[-1] or log_group
            # Structured events: the fields live in the JSON body. Plain
            # lines: the level is read from the line, the service from the
            # stream name (ECS / EKS name streams after the container).
            record = {}
            if message.lstrip().startswith("{"):
                try:
                    parsed = json.loads(message)
                    record = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    record = {}
            body = first_present(record, MESSAGE_FIELDS, default="") if record else ""
            text = body if isinstance(body, str) and body else message
            entry = LogEntry.from_record(
                record,
                raw_id=fields.get("@ptr", ""),
                timestamp=_parse_timestamp(fields.get("@timestamp", "")),
                message=text,
                level=level_of(record, text),
                labels={**record, "_index": group, "log_group": group, "log_stream": log_stream},
            )
            if not entry.service:
                entry.service = log_stream.split("/")[0] if "/" in log_stream else log_stream
            if not entry.host:
                entry.host = log_stream
            entries.append(entry)
        return entries
