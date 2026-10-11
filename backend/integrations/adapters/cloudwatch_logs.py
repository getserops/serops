"""
AWS CloudWatch Logs Adapter for LogProvider.

Implements the LogProvider ABC using boto3 CloudWatch Logs client.
Uses CloudWatch Logs Insights for querying (async start_query → poll get_query_results).
"""
import logging
import time
from datetime import datetime
from typing import List, Tuple, Optional

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import LogEntry, LogStream, LogQuery, _parse_timestamp, _detect_level

logger = logging.getLogger(__name__)


def _get_boto3_client(service: str, config: dict):
    """Create a boto3 client with optional explicit credentials."""
    try:
        import boto3
    except ImportError:
        raise ImportError(
            "boto3 is required for CloudWatch integration. "
            "Install it with: pip install boto3"
        )
    kwargs = {
        "service_name": service,
        "region_name": config.get("aws_region", "us-east-1"),
    }
    # Explicit credentials (if not using IAM role / instance profile)
    access_key = config.get("aws_access_key_id")
    secret_key = config.get("aws_secret_access_key")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
    session_token = config.get("aws_session_token")
    if session_token:
        kwargs["aws_session_token"] = session_token
    return boto3.client(**kwargs)


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
        log_group = index if index else self.default_log_group

        # Translate LogQuery → Insights query if needed
        if isinstance(query, LogQuery):
            insights_query = query.to_cloudwatch_insights()
            size = query.max_results
            if not time_range and query.time_range:
                time_range = query.time_range
        else:
            insights_query = self._build_query(query)

        # Time range defaults to last 1 hour
        now = datetime.utcnow()
        if time_range:
            start_dt, end_dt = time_range
        else:
            start_dt = datetime(now.year, now.month, now.day, now.hour - 1)
            end_dt = now

        try:
            response = self.client.start_query(
                logGroupName=log_group,
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
        """List CloudWatch log groups (analogous to indices)."""
        try:
            raw_name = project.name if hasattr(project, "name") else str(project)
            prefix = f"/aws/{raw_name.lower()}"

            result = self.client.describe_log_groups(
                logGroupNamePrefix=prefix, limit=50
            )
            return [
                g["logGroupName"] for g in result.get("logGroups", [])
            ]
        except Exception as exc:
            logger.warning("CloudWatch get_indices failed: %s", exc)
            return []

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

            # Skip the @ptr field (internal pointer)
            message = fields.get("@message", "")
            timestamp_str = fields.get("@timestamp", "")
            log_stream = fields.get("@logStream", "")

            entries.append(
                LogEntry(
                    timestamp=_parse_timestamp(timestamp_str),
                    message=message,
                    level=_detect_level(fields.get("@log.level", "INFO")),
                    service=log_stream.split("/")[0] if "/" in log_stream else log_stream,
                    host=fields.get("@logStream", ""),
                    labels={
                        "_index": log_group,
                        "log_group": log_group,
                        "log_stream": log_stream,
                    },
                    raw_id=fields.get("@ptr", ""),
                )
            )
        return entries
