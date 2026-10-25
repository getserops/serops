"""
Splunk Enterprise / Splunk Cloud Adapter for LogProvider.

Uses Splunk's REST API directly via ``requests`` — no splunk-sdk
dependency, keeping the container slim. The search API is asynchronous:
we POST a search job (get back a SID), then poll ``/results`` until
Splunk reports the job done.

Auth model: bearer token.  Splunk supports two kinds:
  - Session token (interactive) — short-lived, not our target
  - Authentication token (created via Settings → Tokens) — long-lived,
    exactly what a headless integration should use. Store it in the
    ``password`` field on ObservabilityIntegration so it goes through
    Fernet-encryption like every other credential.

Endpoints used:
  - POST  /services/search/jobs         — start async search
  - GET   /services/search/jobs/{sid}   — poll job status
  - GET   /services/search/jobs/{sid}/results?output_mode=json
                                        — fetch results
  - GET   /services/data/indexes        — health check + get_indices

The adapter deliberately does NOT implement ``index()``. Splunk ingest
is done via HTTP Event Collector (HEC) which is a completely different
endpoint pattern, credential, and error surface; wiring it here would
be a footgun. If HEC ingest is ever needed, add a separate
``SplunkHECIndexer`` — keep the search adapter focused on search.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import requests
from requests.exceptions import RequestException

from integrations.base import LogProvider, LogProviderCapabilities
from integrations.schemas import (
    LogEntry,
    LogQuery,
    _detect_level,
    _parse_timestamp,
)

logger = logging.getLogger(__name__)


class SplunkLogProvider(LogProvider):
    """
    Splunk Enterprise / Splunk Cloud log provider.

    Config (from ObservabilityIntegration):
        host               Base URL, e.g. https://splunk.company.com:8089
        password           Splunk auth token (bearer). Encrypted at rest.
        extra_config:
            index          Default Splunk index to search (default 'main')
            app            App context for search (default '-')
            owner          Owner context (default '-')
            verify_ssl     Whether to verify TLS (default True)
    """

    capabilities = LogProviderCapabilities(
        full_text=True,
        regex=True,
        aggregations=True,
        tail=False,
        max_query_window_days=30,
        indexing=False,
    )

    # Async search job polling. Splunk populates results incrementally
    # — DispatchState==DONE means "no more will come".
    POLL_INTERVAL_SECONDS = 0.5
    MAX_POLL_ATTEMPTS = 120  # ~60 seconds — matches CloudWatch adapter

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        host = (self._config.get("host") or "").rstrip("/")
        if not host:
            raise ValueError("Splunk adapter requires 'host' in config")

        self._base_url = host
        self._index = self._config.get("index", "main")
        self._app = self._config.get("app", "-")
        self._owner = self._config.get("owner", "-")
        self._verify_ssl = bool(self._config.get("verify_ssl", True))

        token = self._config.get("password") or self._config.get("token") or ""
        if not token:
            raise ValueError(
                "Splunk adapter requires an auth token in the 'password' field "
                "(create it in Splunk under Settings → Tokens)"
            )

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            # Splunk returns XML by default; every endpoint we call
            # supports ?output_mode=json but setting it as a session
            # default reduces per-request boilerplate.
            "Accept": "application/json",
        })
        self._session.verify = self._verify_ssl

    # ------------------------------------------------------------------
    # LogProvider ABC
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """Ping the indexes endpoint — cheapest authenticated call.

        A 200 with an ``entry`` list means the token is valid *and* has
        capability to read index metadata (which every user with search
        rights does). Anything else — 401, 403, network error — is
        treated as unhealthy.
        """
        try:
            resp = self._session.get(
                urljoin(self._base_url + "/", "services/data/indexes"),
                params={"output_mode": "json", "count": 1},
                timeout=self.timeout_seconds,
            )
            return resp.status_code == 200
        except RequestException as exc:
            logger.error("Splunk health check failed: %s", exc)
            return False

    def search(
        self,
        index: str,
        query,  # dict (legacy) or LogQuery
        time_range: Optional[Tuple[datetime, datetime]] = None,
        size: int = 5000,
    ) -> List[LogEntry]:
        """Run an SPL search job and return canonical LogEntry list.

        ``index`` picks the Splunk index; empty falls back to the
        adapter default (usually 'main'). Non-string or dangerous
        values are rejected in :meth:`LogQuery.to_splunk_spl` via
        ``_spl_token``.
        """
        target_index = index or self._index
        if "," in target_index:
            # The batch code joins whatever get_indices() returned. Splunk's
            # bareword check rejects a comma list outright ("Invalid SPL
            # token"), and the error used to leave every analysis empty.
            target_index = self._index

        # Build SPL. Accept both LogQuery and legacy dict for parity
        # with the other adapters — dict path just embeds the raw
        # ``spl`` string a caller supplied.
        if isinstance(query, LogQuery):
            spl = query.to_splunk_spl(index=target_index)
            size = query.max_results
            if not time_range and query.time_range:
                time_range = query.time_range
        elif isinstance(query, dict):
            spl = query.get("spl") or f"search index={target_index}"
        else:
            raise TypeError(
                f"Splunk search: unsupported query type {type(query).__name__}"
            )

        # earliest / latest passed as params — separate from the SPL
        # so we don't have to lex-quote timestamps into the string.
        if time_range:
            start_dt, end_dt = time_range
        else:
            end_dt = datetime.utcnow()
            start_dt = end_dt - timedelta(hours=1)

        try:
            sid = self._start_job(spl, start_dt, end_dt)
            if not sid:
                return []
            if not self._wait_for_job(sid):
                return []
            return self._fetch_results(sid, max_count=size, index=target_index)
        except RequestException as exc:
            logger.error("Splunk search failed: %s", exc)
            return []

    def get_indices(self, project) -> List[str]:
        """The configured index (``extra_config.index``, default 'main'), if
        the token can see it.

        Splunk indexes are global, not project-scoped; SPL filters down to
        the project. This used to return every index visible to the token
        (``_internal``, ``_audit``, ...), which the batch code joined into
        one comma list that the SPL bareword check rejects, so scheduled
        analyses and investigations never got a log (found by the journey
        suite, launch plan 9.9).
        """
        try:
            resp = self._session.get(
                urljoin(self._base_url + "/", "services/data/indexes"),
                params={"output_mode": "json", "count": 200},
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
            visible = {entry.get("name") for entry in data.get("entry", [])}
            if self._index in visible:
                return [self._index]
            logger.warning("Splunk index %r is not visible to the token (has: %s)",
                           self._index, ", ".join(sorted(n for n in visible if n)))
            return []
        except RequestException as exc:
            logger.warning("Splunk get_indices failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _start_job(self, spl: str, start_dt: datetime, end_dt: datetime) -> Optional[str]:
        """POST a search job. Splunk replies with the search ID (SID)."""
        payload = {
            "search": spl,
            "earliest_time": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "latest_time": end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "output_mode": "json",
            # ``exec_mode=normal`` starts async. ``blocking`` would
            # tie up the request thread for the whole search — bad for
            # our worker pool. Polling is cheap and matches CloudWatch.
            "exec_mode": "normal",
        }
        resp = self._session.post(
            self._job_endpoint(),
            data=payload,
            timeout=self.timeout_seconds,
        )
        if resp.status_code >= 400:
            logger.error(
                "Splunk start_job failed status=%s body=%s",
                resp.status_code, resp.text[:200],
            )
            return None
        try:
            return resp.json().get("sid")
        except ValueError:
            logger.error("Splunk start_job returned non-JSON: %s", resp.text[:200])
            return None

    def _wait_for_job(self, sid: str) -> bool:
        """Poll job status until DispatchState==DONE or timeout."""
        job_url = f"{self._job_endpoint()}/{sid}"
        for _ in range(self.MAX_POLL_ATTEMPTS):
            try:
                resp = self._session.get(
                    job_url,
                    params={"output_mode": "json"},
                    timeout=self.timeout_seconds,
                )
                if resp.status_code == 404:
                    logger.warning("Splunk job %s vanished before completion", sid)
                    return False
                if resp.status_code >= 400:
                    logger.error(
                        "Splunk job poll failed sid=%s status=%s",
                        sid, resp.status_code,
                    )
                    return False
                entries = resp.json().get("entry", [])
                if not entries:
                    return False
                content = entries[0].get("content", {})
                state = content.get("dispatchState", "")
                if state == "DONE":
                    return True
                if state in ("FAILED", "INTERNAL_CANCEL", "USER_CANCEL", "BAD_INPUT_CANCEL"):
                    logger.warning(
                        "Splunk job %s ended in state=%s messages=%s",
                        sid, state, content.get("messages", []),
                    )
                    return False
            except RequestException as exc:
                logger.error("Splunk job poll error sid=%s: %s", sid, exc)
                return False
            time.sleep(self.POLL_INTERVAL_SECONDS)

        logger.warning("Splunk job %s did not complete within poll budget", sid)
        return False

    def _fetch_results(self, sid: str, max_count: int, index: str) -> List[LogEntry]:
        """Fetch completed job results and normalise to LogEntry."""
        results_url = f"{self._job_endpoint()}/{sid}/results"
        try:
            resp = self._session.get(
                results_url,
                params={
                    "output_mode": "json",
                    # Splunk caps this at 50000 per page; we page in a
                    # single call which is enough for our 5–10k typical
                    # batch. Higher counts should re-page (future work).
                    "count": min(max_count, 50000),
                    # Without a field list /results returns only Splunk's
                    # default fields, so service_name and log_level were
                    # missing from every row.
                    "f": "*",
                },
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            data = resp.json()
        except (RequestException, ValueError) as exc:
            logger.error("Splunk fetch_results failed sid=%s: %s", sid, exc)
            return []

        entries: List[LogEntry] = []
        for row in data.get("results", []):
            row = _with_json_fields(row)
            # Splunk gives us ``_time`` (epoch string or ISO), ``_raw``
            # (the log line), plus every extracted field. We map the
            # canonical fields explicitly and shove the rest into
            # labels for downstream filtering.
            raw_ts = row.get("_time", "")
            timestamp = _parse_timestamp(raw_ts) if raw_ts else datetime.min
            entries.append(
                LogEntry(
                    timestamp=timestamp,
                    message=row.get("message") or row.get("_raw", ""),
                    level=_detect_level(row.get("log_level", row.get("level", "INFO"))),
                    service=row.get("service_name", row.get("service", "")),
                    host=row.get("host", ""),
                    trace_id=row.get("trace_id", ""),
                    raw_id=row.get("_cd", ""),  # Splunk internal doc id
                    labels={
                        "_index": index,
                        **{
                            k: v for k, v in row.items()
                            if not k.startswith("_") and k not in (
                                "message", "level", "log_level",
                                "service", "service_name", "host", "trace_id",
                            )
                        },
                    },
                )
            )
        return entries

    def _job_endpoint(self) -> str:
        """Build the /jobs endpoint path with owner+app context.

        Splunk namespaces every REST endpoint under
        ``/servicesNS/{owner}/{app}`` — using ``-`` for either means
        "any". Keeping this configurable lets us hit a specific app's
        indexes if the token is scoped, and defaults to open access.
        """
        return urljoin(
            self._base_url + "/",
            f"servicesNS/{self._owner}/{self._app}/search/jobs",
        )


def _with_json_fields(row: dict) -> dict:
    """Fill canonical fields from a JSON ``_raw`` that Splunk did not extract.

    HEC shippers (Fluent Bit, the OTel collector, Vector) send each event as
    JSON; unless the sourcetype extracts it, the canonical fields live only
    inside ``_raw``. Without them every entry had an empty service, and the
    batch code's registered-service filter dropped all of them, so Splunk
    analyses came back "quiet" (found by the journey suite, launch plan 9.9).
    Fields Splunk already returned win.
    """
    raw = row.get("_raw")
    if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
        return row
    try:
        event = json.loads(raw)
    except ValueError:
        return row
    if not isinstance(event, dict):
        return row
    merged = dict(row)
    for key in ("service_name", "service", "log_level", "level", "message", "environment",
                "project_name", "organisation_name", "host", "trace_id"):
        value = event.get(key)
        if value not in (None, "") and not merged.get(key):
            merged[key] = value if isinstance(value, str) else str(value)
    return merged
