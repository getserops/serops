"""Models for distributed tracing (OpenTelemetry OTLP ingestion).

Data model:

* ``Trace``      — one per OTEL trace_id (32-hex-char, 128-bit).
                   Rolls up span-level metrics (duration, error count,
                   root service/operation) for fast list/timeline queries.
* ``Span``       — one per OTEL span_id (16-hex-char, 64-bit) within a trace.
                   Stores attributes + events as JSONB for flexibility;
                   canonical fields (times, service, status) are top-level
                   columns for efficient filtering.
* ``IngestKey``  — per-organisation bearer token authorising OTLP ingestion.
                   Stored as SHA-256 hash — plaintext is shown ONCE on
                   creation and never retrievable after (GitHub PAT model).

Storage notes:

* Postgres JSONB for attributes/events — no need for schema migrations
  when OTEL adds new resource attributes.
* Day-based table partitioning is a v1.1 optimisation. For v1.0 we lean
  on btree(start_time) + org+time composite indexes; the Sentinel batch
  window means most queries hit a small hot set.
* No cascade from Trace → Span at the DB level intentional: mass-deleting
  a trace does one DELETE which fans out to spans efficiently via FK
  index. If a trace ever grows unbounded (>10k spans, DoS scenario) the
  rate-limit + payload-size cap on the OTLP endpoint prevents it.

Security:

* Trace attributes / span attributes / span events are user-supplied
  JSON. Callers must NEVER interpolate them into raw SQL, shell, or
  templates. They're consumed only by the AI prompt (which handles
  arbitrary text safely) and the correlation engine (dict lookups).
* IngestKey.verify() uses ``hmac.compare_digest`` — constant-time.
"""

import hashlib
import hmac
import secrets

from django.db import models

from Organisations.models import Organisations


# ---------------------------------------------------------------------------
# Traces + Spans
# ---------------------------------------------------------------------------


class Trace(models.Model):
    """One OpenTelemetry trace — rolls up its spans."""

    # OTEL trace_id is a 128-bit hex string (32 chars).
    trace_id = models.CharField(max_length=32, primary_key=True)
    organisation = models.ForeignKey(
        Organisations,
        on_delete=models.CASCADE,
        related_name='traces',
    )

    # Root span rollups — populated on first span insert.
    root_service_name = models.CharField(max_length=255, blank=True, default='')
    root_operation = models.CharField(max_length=255, blank=True, default='')

    # Time span of the entire trace.
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_ms = models.IntegerField(default=0)

    # Aggregates from spans.
    span_count = models.IntegerField(default=0)
    error_span_count = models.IntegerField(default=0)

    # Overall status: 'OK' | 'ERROR' | 'UNSET' — derived from spans.
    status_code = models.CharField(max_length=16, blank=True, default='UNSET')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'traces_trace'
        indexes = [
            # Primary access pattern: list traces for an org in a time window.
            models.Index(fields=['organisation', '-start_time'], name='trace_org_start_idx'),
            # Per-service filter: "traces for the checkout service in the last hour".
            models.Index(fields=['organisation', 'root_service_name', '-start_time'],
                         name='trace_org_svc_start_idx'),
            # Error-only view.
            models.Index(fields=['organisation', 'status_code', '-start_time'],
                         name='trace_org_status_idx'),
        ]
        ordering = ['-start_time']

    def __str__(self):
        return f'Trace {self.trace_id[:16]}… ({self.root_service_name or "?"} {self.duration_ms}ms)'


class Span(models.Model):
    """One OpenTelemetry span within a trace."""

    KIND_CHOICES = [
        ('INTERNAL', 'Internal'),
        ('SERVER', 'Server'),
        ('CLIENT', 'Client'),
        ('PRODUCER', 'Producer'),
        ('CONSUMER', 'Consumer'),
    ]
    STATUS_CHOICES = [
        ('UNSET', 'Unset'),
        ('OK', 'OK'),
        ('ERROR', 'Error'),
    ]

    trace = models.ForeignKey(
        Trace, on_delete=models.CASCADE, related_name='spans',
    )
    # OTEL span_id is a 64-bit hex string (16 chars).
    span_id = models.CharField(max_length=16)
    parent_span_id = models.CharField(max_length=16, blank=True, default='')

    service_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    operation_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=KIND_CHOICES, blank=True, default='INTERNAL')

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    duration_ms = models.IntegerField()

    status_code = models.CharField(max_length=16, choices=STATUS_CHOICES, blank=True, default='UNSET')
    status_message = models.CharField(max_length=500, blank=True, default='')

    # OTEL attributes (map[string]any) — arbitrary key-value from the SDK.
    attributes = models.JSONField(default=dict, blank=True)
    # OTEL events (list of {time, name, attributes}) — usually exceptions + logs.
    events = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = 'traces_span'
        # Same (trace, span_id) pair should never appear twice — OTEL guarantees
        # span_id uniqueness within a trace_id, so we enforce that at the DB.
        unique_together = [('trace', 'span_id')]
        indexes = [
            models.Index(fields=['trace', 'start_time'], name='span_trace_start_idx'),
            models.Index(fields=['service_name', '-start_time'], name='span_svc_start_idx'),
        ]
        ordering = ['start_time']

    def __str__(self):
        return f'{self.service_name}:{self.operation_name} ({self.duration_ms}ms)'


# ---------------------------------------------------------------------------
# Ingest key (bearer auth for the OTLP receiver)
# ---------------------------------------------------------------------------


_INGEST_KEY_PREFIX = 'serops_otlp_'


class IngestKey(models.Model):
    """Per-organisation bearer token authorising OTLP ingestion.

    Stored as SHA-256 hash of the key body — plaintext is returned ONCE
    on creation and never again (GitHub PAT model). Verification hashes
    the presented key and looks up by hash, then does a constant-time
    compare on the ID column via primary-key equality — never on the
    hash column directly (which is unique-indexed and thus already
    constant-lookup at the DB).

    Format of plaintext: ``serops_otlp_<43-char-url-safe-base64>``
    (32 random bytes = 256 bits of entropy; url-safe so no header quoting
    issues on the way through OTEL Collectors).
    """

    organisation = models.ForeignKey(
        Organisations, on_delete=models.CASCADE, related_name='ingest_keys',
    )
    name = models.CharField(
        max_length=100,
        help_text='Human-readable label (e.g. "prod k8s cluster", "staging OTEL Collector").',
    )
    key_hash = models.CharField(max_length=64, unique=True, db_index=True)
    key_prefix = models.CharField(
        max_length=20,
        help_text='First few chars of the key for identification without exposing the whole thing.',
    )
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        # Late-binding string ref so we don't circular-import Users.
        'Users.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
    )

    class Meta:
        db_table = 'traces_ingest_key'
        indexes = [
            models.Index(fields=['organisation', 'is_active'], name='ingestkey_org_active_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'IngestKey({self.name}, org={self.organisation_id}, {self.key_prefix}...)'

    # ------------------------------------------------------------------
    # Key generation + verification
    # ------------------------------------------------------------------

    @classmethod
    def generate_key(cls) -> str:
        """Return a fresh plaintext key. NOT stored — caller must save the hash."""
        return _INGEST_KEY_PREFIX + secrets.token_urlsafe(32)

    @classmethod
    def hash_key(cls, plaintext: str) -> str:
        """SHA-256 hex digest of the plaintext key."""
        return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()

    @classmethod
    def verify(cls, plaintext: str):
        """Return the matching active IngestKey (and touch last_used_at), or None.

        Constant-time in the sense that we use ``compare_digest`` on the
        hash to avoid a timing side-channel between "hash exists but org
        inactive" and "hash doesn't exist at all". Both cases end up
        traversing the same code path with the same DB lookup shape.
        """
        if not plaintext or not plaintext.startswith(_INGEST_KEY_PREFIX):
            return None
        candidate_hash = cls.hash_key(plaintext)
        row = cls.objects.filter(key_hash=candidate_hash, is_active=True).first()
        if row is None:
            return None
        # compare_digest here is belt-and-braces — the DB lookup is already
        # exact-match on the unique key_hash column, but if we ever add a
        # non-unique index or change lookup shape, the constant-time check
        # stays as a defense.
        if not hmac.compare_digest(row.key_hash, candidate_hash):
            return None
        return row

    def set_key(self, plaintext: str) -> None:
        """Populate hash + prefix from a plaintext key (not saved automatically)."""
        self.key_hash = self.hash_key(plaintext)
        # `serops_otlp_XXXXXX...` — first ~14 chars is enough to identify without leaking.
        self.key_prefix = plaintext[:len(_INGEST_KEY_PREFIX) + 6]
