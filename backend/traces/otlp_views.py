"""OpenTelemetry OTLP HTTP receiver — accepts spans from OTEL Collectors.

Endpoint:

    POST /api/traces/v1/traces
    Content-Type: application/json  OR  application/x-protobuf
    Authorization: Bearer <ingest_key>

    JSON body:
        { "resourceSpans": [ { "resource": { "attributes": [...] },
                               "scopeSpans": [ { "spans": [ ... ] } ] } ] }

    Protobuf body: OTLP ExportTraceServiceRequest wire format.

Standard OTLP/HTTP encoding per the OpenTelemetry spec:
    https://opentelemetry.io/docs/specs/otlp/#otlphttp

Both content-types are accepted because the Python OTel SDK's default
HTTP trace exporter sends protobuf, while custom callers (curl,
tests, low-dep clients) send JSON. E31-6 fix — previously the
receiver only accepted JSON and rejected the SDK-default protobuf
with 415.

gRPC support is deferred to v1.1 (requires grpcio-tools).

Security:

* Bearer token auth via ``IngestKey.verify()`` — SHA-256 hashed at
  rest, constant-time compare.
* Rate-limited to 3000 requests/min per org via ScopedRateThrottle
  ``otlp_ingest`` — sized for high-traffic K8s (a busy cluster emits
  hundreds of spans/sec, batched by the OTEL Collector so ~10-50 HTTP
  requests/sec normally).
* Payload capped at 5 MB (Django ``DATA_UPLOAD_MAX_MEMORY_SIZE``).
* Span attributes / events passed through as-is to Postgres JSONB —
  never interpolated into SQL / shell / templates.
* Resource attributes checked for ``service.name`` (canonical) and
  aliases via ``integrations.field_aliases`` — SerOps' log/metric
  alias policy applies to traces too.
"""

import gzip
import json
import logging
import zlib
from datetime import datetime, timezone

from django.db import transaction
from rest_framework import status
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView


class RawBytesParser(BaseParser):
    """Passthrough parser that hands the raw request bytes to the view.

    Used for OTLP protobuf ingest — DRF's default parsers would reject
    ``application/x-protobuf`` with 415 before our view could decode it
    with the opentelemetry-proto schema.
    """
    media_type = 'application/x-protobuf'

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()

from integrations.field_aliases import (
    ENVIRONMENT_ALIASES,
    SERVICE_NAME_ALIASES,
    first_present,
)
from .models import IngestKey, Span, Trace
from .otlp_parsing import (
    parse_attributes as _parse_attributes_shared,
    parse_events as _parse_events_shared,
    parse_kind as _parse_kind_shared,
    parse_span_dict as _parse_span_shared,
)

logger = logging.getLogger(__name__)


class OTLPTracesReceiver(APIView):
    """Ingest OTLP/HTTP traces (JSON or protobuf body)."""

    permission_classes = [AllowAny]  # bearer token, not Django auth
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'otlp_ingest'

    # Accept JSON (OTLP HTTP JSON spec) + application/x-protobuf
    # (Python OTel SDK default). RawBytesParser hands us the raw
    # bytes; we decode with the opentelemetry-proto schema below.
    parser_classes = [JSONParser, RawBytesParser]

    def post(self, request):
        # 1. Bearer auth
        ingest_key = self._authenticate(request)
        if ingest_key is None:
            return Response(
                {'error': 'Missing or invalid Authorization: Bearer <ingest_key>'},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        org = ingest_key.organisation

        # 2. Decompress if needed.
        #
        # The OpenTelemetry Collector's otlphttp exporter compresses with
        # gzip BY DEFAULT, and Django does not decompress request bodies
        # (GZipMiddleware only touches responses). Every default-configured
        # collector therefore had its whole payload rejected: protobuf
        # ParseFromString saw gzip bytes and failed, and the receiver
        # answered 400. Verified against a real collector — with gzip, 48
        # spans dropped; with `compression: none`, the same traffic ingested
        # fine. The default is what has to work.
        raw_body, encoding_error = self._decompress(
            request.body, request.headers.get('Content-Encoding'),
        )
        if encoding_error:
            return Response(
                {'error': encoding_error},
                status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        # 3. Parse payload — JSON or protobuf.
        #
        # Parsed from raw_body rather than request.data throughout. Reading
        # request.body (needed for decompression) makes a later request.data
        # access raise, and going through the raw bytes keeps both encodings
        # on one path.
        content_type = (request.content_type or '').split(';')[0].strip().lower()
        if content_type == 'application/x-protobuf':
            payload = self._decode_protobuf(raw_body)
            if payload is None:
                return Response(
                    {'error': 'Malformed OTLP protobuf payload'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # JSON is the default (per OTLP HTTP spec, absent Content-Type
            # implies JSON).
            try:
                payload = json.loads(raw_body or b'{}')
            except (ValueError, UnicodeDecodeError) as exc:
                logger.warning('OTLP JSON decode failed: %s', exc)
                return Response(
                    {'error': 'Malformed OTLP JSON payload'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if not isinstance(payload, dict):
            return Response(
                {'error': 'Body must decode to an object with resourceSpans'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        resource_spans_list = payload.get('resourceSpans') or []
        if not isinstance(resource_spans_list, list):
            return Response(
                {'error': 'resourceSpans must be a list'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 3. Ingest — a single DB transaction for the whole request so
        #    a mid-request failure doesn't leave partial spans.
        try:
            with transaction.atomic():
                accepted_spans, accepted_traces = self._ingest(resource_spans_list, org)
        except Exception as e:
            logger.exception('OTLP ingest failed for org %s: %s', org.id, e)
            return Response(
                {'error': 'Failed to persist spans'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 4. Touch last_used_at (outside the txn — best-effort telemetry).
        try:
            IngestKey.objects.filter(pk=ingest_key.pk).update(
                last_used_at=datetime.now(timezone.utc),
            )
        except Exception:
            pass

        # 5. Self-metrics (Item #24).
        try:
            from Data.self_metrics import OTLP_SPANS_RECEIVED
            OTLP_SPANS_RECEIVED.inc(accepted_spans or 0)
        except Exception:
            pass

        return Response({
            'accepted_spans': accepted_spans,
            'accepted_traces': accepted_traces,
        })

    # ------------------------------------------------------------------
    # Protobuf decoding
    # ------------------------------------------------------------------

    @staticmethod
    def _decompress(raw_bytes, content_encoding):
        """Undo Content-Encoding on the request body.

        Returns ``(bytes, None)`` on success or ``(None, message)`` when the
        encoding is unsupported or the body is corrupt.

        gzip is what matters in practice: it is the otlphttp exporter's
        default. deflate is in the OTLP spec and free to support from the
        stdlib. zstd is accepted by the spec but needs a third-party
        library, so it gets an explicit message naming the fix rather than a
        generic decode failure that looks like malformed data.
        """
        encoding = (content_encoding or '').strip().lower()
        if not encoding or encoding == 'identity':
            return raw_bytes, None
        try:
            if encoding == 'gzip':
                return gzip.decompress(raw_bytes), None
            if encoding == 'deflate':
                return zlib.decompress(raw_bytes), None
        except Exception as exc:
            logger.warning('OTLP %s decompression failed: %s', encoding, exc)
            return None, f'Body is not valid {encoding} data'
        return None, (
            f'Unsupported Content-Encoding "{encoding}". Use gzip, deflate, '
            f'or none.'
        )

    @staticmethod
    def _decode_protobuf(raw_bytes):
        """Decode an OTLP ExportTraceServiceRequest into the same dict shape
        that the JSON path produces (``{resourceSpans: [...]}``).

        Returns ``None`` on parse failure so the caller can 400.

        The conversion via ``MessageToDict(preserving_proto_field_name=False)``
        yields camelCase field names — matches OTLP JSON spec verbatim so
        the downstream parser doesn't need to branch on encoding.
        """
        try:
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
                ExportTraceServiceRequest,
            )
            from google.protobuf.json_format import MessageToDict
        except ImportError:
            logger.error(
                'opentelemetry-proto not installed — protobuf OTLP requests '
                'rejected. Install `opentelemetry-proto>=1.27` and restart.'
            )
            return None
        try:
            msg = ExportTraceServiceRequest()
            msg.ParseFromString(raw_bytes)
            # ``preserving_proto_field_name=False`` yields camelCase field
            # names, matching the OTLP JSON spec verbatim.
            # ``use_integers_for_enums=True`` keeps ``span.kind`` as its
            # numeric enum value (1-5) instead of the string
            # ``"SPAN_KIND_SERVER"`` — matches the shared parser's
            # expectation (it looks up ``KIND_MAP`` by int/hex-like key).
            return MessageToDict(
                msg,
                preserving_proto_field_name=False,
                use_integers_for_enums=True,
            )
        except Exception as exc:
            logger.warning('OTLP protobuf decode failed: %s', exc)
            return None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    @staticmethod
    def _authenticate(request):
        header = request.META.get('HTTP_AUTHORIZATION', '')
        if not header.lower().startswith('bearer '):
            return None
        plaintext = header[len('Bearer '):].strip()
        return IngestKey.verify(plaintext)

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def _ingest(self, resource_spans_list, org):
        """Parse OTLP resource-spans and persist. Returns (span_count, trace_count)."""
        # trace_id → aggregated stats we'll write to the Trace row.
        trace_stats = {}
        # New Span objects (bulk-created below).
        new_spans = []
        # Resource-level attributes indexed by (resource attrs id in this batch),
        # so we can look up service_name / environment per span.
        # OTLP: each resourceSpans entry has its own resource; spans within it
        # inherit those resource attributes.

        for res_spans in resource_spans_list:
            if not isinstance(res_spans, dict):
                continue
            resource_attrs = self._parse_attributes(
                (res_spans.get('resource') or {}).get('attributes') or []
            )
            # Resource-level service_name — aliases: `service.name` (OTEL canonical),
            # `service_name` (SerOps canonical). Both are valid via alias support.
            service_name_from_resource = first_present(
                resource_attrs, SERVICE_NAME_ALIASES, default='',
            )

            scope_spans_list = res_spans.get('scopeSpans') or []
            for scope_spans in scope_spans_list:
                for span_dict in (scope_spans.get('spans') or []):
                    parsed = self._parse_span(span_dict, resource_attrs, service_name_from_resource)
                    if parsed is None:
                        continue

                    trace_id = parsed['trace_id']

                    # Track rollup stats per trace.
                    stats = trace_stats.setdefault(trace_id, {
                        'start_time': parsed['start_time'],
                        'end_time': parsed['end_time'],
                        'span_count': 0,
                        'error_span_count': 0,
                        'root_service_name': '',
                        'root_operation': '',
                        'has_error': False,
                    })
                    stats['start_time'] = min(stats['start_time'], parsed['start_time'])
                    stats['end_time'] = max(stats['end_time'], parsed['end_time'])
                    stats['span_count'] += 1
                    if parsed['status_code'] == 'ERROR':
                        stats['error_span_count'] += 1
                        stats['has_error'] = True
                    # Root span = span with no parent_span_id.
                    if not parsed['parent_span_id']:
                        stats['root_service_name'] = parsed['service_name']
                        stats['root_operation'] = parsed['operation_name']

                    # Prepare Span row (link to trace happens below after upsert).
                    new_spans.append((trace_id, parsed))

        if not new_spans:
            return 0, 0

        # Upsert Trace rows (one per trace_id in this batch).
        traces = self._upsert_traces(trace_stats, org)

        # Now materialise Span rows with FK to the Trace.
        span_objects = []
        for trace_id, parsed in new_spans:
            trace = traces.get(trace_id)
            if trace is None:
                continue
            span_objects.append(Span(
                trace=trace,
                span_id=parsed['span_id'],
                parent_span_id=parsed['parent_span_id'],
                service_name=parsed['service_name'],
                operation_name=parsed['operation_name'],
                kind=parsed['kind'],
                start_time=parsed['start_time'],
                end_time=parsed['end_time'],
                duration_ms=parsed['duration_ms'],
                status_code=parsed['status_code'],
                status_message=parsed['status_message'],
                attributes=parsed['attributes'],
                events=parsed['events'],
            ))

        # ignore_conflicts so a resent batch (OTLP retry) doesn't 500.
        Span.objects.bulk_create(span_objects, batch_size=500, ignore_conflicts=True)

        return len(span_objects), len(traces)

    def _upsert_traces(self, trace_stats, org):
        """Create-or-update Trace rows for every trace_id seen in this batch."""
        result = {}
        for trace_id, stats in trace_stats.items():
            duration_ms = int((stats['end_time'] - stats['start_time']).total_seconds() * 1000)
            status_code = 'ERROR' if stats['has_error'] else 'OK'

            # Get-or-create per trace_id. On update, we ADD span counts (a trace
            # may span multiple OTLP batches as it grows).
            trace, created = Trace.objects.get_or_create(
                trace_id=trace_id,
                defaults={
                    'organisation': org,
                    'start_time': stats['start_time'],
                    'end_time': stats['end_time'],
                    'duration_ms': duration_ms,
                    'span_count': stats['span_count'],
                    'error_span_count': stats['error_span_count'],
                    'status_code': status_code,
                    'root_service_name': stats['root_service_name'],
                    'root_operation': stats['root_operation'],
                },
            )
            if not created:
                # Update rollups if this batch extends the trace.
                trace.start_time = min(trace.start_time, stats['start_time'])
                trace.end_time = max(trace.end_time, stats['end_time'])
                trace.duration_ms = int(
                    (trace.end_time - trace.start_time).total_seconds() * 1000
                )
                trace.span_count += stats['span_count']
                trace.error_span_count += stats['error_span_count']
                if stats['has_error']:
                    trace.status_code = 'ERROR'
                if stats['root_service_name']:  # newly-seen root wins
                    trace.root_service_name = stats['root_service_name']
                    trace.root_operation = stats['root_operation']
                trace.save(update_fields=[
                    'start_time', 'end_time', 'duration_ms',
                    'span_count', 'error_span_count', 'status_code',
                    'root_service_name', 'root_operation',
                ])
            result[trace_id] = trace
        return result

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_span(self, span_dict, resource_attrs, resource_service_name):
        """Thin wrapper around the shared parser in traces.otlp_parsing.

        Kept as an instance method for tests + subclasses.
        """
        return _parse_span_shared(span_dict, resource_attrs, resource_service_name)

    @staticmethod
    def _parse_attributes(attrs_list):
        return _parse_attributes_shared(attrs_list)

    @staticmethod
    def _parse_kind(raw):
        return _parse_kind_shared(raw)

    def _parse_events(self, events_list):
        return _parse_events_shared(events_list)
