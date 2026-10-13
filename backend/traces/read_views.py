"""Read APIs for distributed traces.

Endpoints under ``/api/traces/``:

    GET    /traces/                     — list traces (paginated, filtered)
    GET    /traces/<trace_id>/          — trace detail with all spans
    GET    /services/                   — distinct service names for filter UI

Filters on the list endpoint:

    ?service=checkout
    ?status=OK|ERROR|UNSET
    ?min_duration_ms=100
    ?since=2026-09-04T00:00:00Z
    ?until=2026-09-04T23:59:59Z

Multi-tenancy: everything is scoped to ``request.user.organisation``.
Attributes / events are user-supplied JSON so they're returned as-is
but never interpolated into SQL or shell.
"""

from datetime import datetime

from django.utils.dateparse import parse_datetime
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Span, Trace


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class TraceListSerializer(serializers.ModelSerializer):
    """Trimmed shape for list views — no attributes, no spans."""

    class Meta:
        model = Trace
        fields = [
            'trace_id', 'root_service_name', 'root_operation',
            'start_time', 'end_time', 'duration_ms',
            'span_count', 'error_span_count', 'status_code',
        ]


class SpanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Span
        fields = [
            'span_id', 'parent_span_id',
            'service_name', 'operation_name', 'kind',
            'start_time', 'end_time', 'duration_ms',
            'status_code', 'status_message',
            'attributes', 'events',
        ]


class TraceDetailSerializer(serializers.ModelSerializer):
    """Full shape — includes every span. Used for the waterfall view."""

    spans = SpanSerializer(many=True, read_only=True)

    class Meta:
        model = Trace
        fields = [
            'trace_id', 'root_service_name', 'root_operation',
            'start_time', 'end_time', 'duration_ms',
            'span_count', 'error_span_count', 'status_code',
            'spans',
        ]


# ---------------------------------------------------------------------------
# ViewSet
# ---------------------------------------------------------------------------


class TracePagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


def _parse_iso(value):
    """Parse an ISO datetime, return None on failure (never raise)."""
    if not value:
        return None
    try:
        parsed = parse_datetime(value)
        return parsed if isinstance(parsed, datetime) else None
    except (ValueError, TypeError):
        return None


class TraceReadViewSet(viewsets.ReadOnlyModelViewSet):
    """Org-scoped read-only access to traces."""

    permission_classes = [IsAuthenticated]
    pagination_class = TracePagination
    lookup_field = 'trace_id'
    # OTEL trace_id = 32 hex chars; DRF's default regex allows too much.
    lookup_value_regex = '[0-9a-fA-F]{32}'

    def get_queryset(self):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            return Trace.objects.none()
        qs = Trace.objects.filter(organisation=org)

        params = self.request.query_params

        service = params.get('service')
        if service:
            qs = qs.filter(root_service_name=service)

        status = params.get('status')
        if status:
            # Normalise: front-end may send lowercase.
            qs = qs.filter(status_code=status.upper())

        min_duration = params.get('min_duration_ms')
        if min_duration:
            try:
                qs = qs.filter(duration_ms__gte=int(min_duration))
            except (TypeError, ValueError):
                # Silently ignore bad input rather than 500 — the filter is
                # optional, and a bad ?min_duration_ms=foo shouldn't take
                # the dashboard down.
                pass

        since = _parse_iso(params.get('since'))
        if since:
            qs = qs.filter(start_time__gte=since)

        until = _parse_iso(params.get('until'))
        if until:
            qs = qs.filter(start_time__lte=until)

        return qs

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return TraceDetailSerializer
        return TraceListSerializer

    def retrieve(self, request, *args, **kwargs):
        # Pre-fetch spans in a single query for waterfall rendering.
        trace = self.get_object()
        # get_object already filtered by org via get_queryset() — safe.
        trace.spans_prefetched = trace.spans.all()
        serializer = self.get_serializer(trace)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def services(self, request):
        """Distinct root service names in the caller's org — for filter dropdowns."""
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return Response([])
        names = (
            Trace.objects
            .filter(organisation=org)
            .exclude(root_service_name='')
            .values_list('root_service_name', flat=True)
            .distinct()
            .order_by('root_service_name')
        )
        return Response(list(names))
