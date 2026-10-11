"""
REST Views for Observability Integration Management.

Single ViewSet for all observability integrations (log + metric providers).
"""

import logging

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from Middlewares.rbac import IsAdminRole
from Data.audit import log_action
from .health import (
    MAX_SAMPLE_SIZE,
    MAX_SAMPLE_WINDOW_MIN,
    MIN_SAMPLE_SIZE,
    MIN_SAMPLE_WINDOW_MIN,
    collect_ingest_health,
)
from .models import Cluster, ObservabilityIntegration, ADAPTER_MAP, _available_capabilities
from .registry import IntegrationRegistry
from .serializers import (
    ClusterSerializer,
    ObservabilityIntegrationSerializer,
    ObservabilityIntegrationListSerializer,
)

logger = logging.getLogger(__name__)


class ObservabilityIntegrationViewSet(viewsets.ModelViewSet):
    """
    CRUD + actions for per-org observability integrations.

    Endpoints (under /integrations/observability/):
        GET    /                   — list integrations for user's org
        POST   /                   — create integration
        GET    /{id}/              — detail
        PATCH  /{id}/              — update
        DELETE /{id}/              — delete
        POST   /{id}/health-check/ — test connection health
        GET    /providers/         — list available provider types

    Multi-tenancy: all queries are scoped to the user's organisation.
    Read operations require authentication; writes require admin role.
    """

    serializer_class = ObservabilityIntegrationSerializer

    def get_permissions(self):
        # `ingest_health` samples recent data from the user's provider and
        # returns a report on tag presence — read-only, no mutation. Any
        # authenticated org member may run it (helps them debug their
        # own tagging config without needing admin escalation).
        if self.action in ('list', 'retrieve', 'available_providers', 'ingest_health'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminRole()]

    # ------------------------------------------------------------------
    # Queryset & serializer
    # ------------------------------------------------------------------

    def get_queryset(self):
        user = self.request.user
        org = getattr(user, 'organisation', None)
        if org:
            return (
                ObservabilityIntegration.objects.filter(organisation=org)
                .order_by('-created_at')
            )
        return ObservabilityIntegration.objects.none()

    def get_serializer_class(self):
        if self.action == 'list':
            return ObservabilityIntegrationListSerializer
        return ObservabilityIntegrationSerializer

    # ------------------------------------------------------------------
    # Create / Update hooks
    # ------------------------------------------------------------------

    def perform_create(self, serializer):
        org = getattr(self.request.user, 'organisation', None)
        if not org:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError('User must belong to an organisation.')
        instance = serializer.save(organisation=org)
        IntegrationRegistry.clear_cache(org_id=org.id)
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'integration_create',
            'provider': instance.provider,
            'name': instance.display_name,
        })

    def perform_update(self, serializer):
        instance = serializer.save()
        org = getattr(self.request.user, 'organisation', None)
        if org:
            IntegrationRegistry.clear_cache(org_id=org.id)
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'integration_update',
            'provider': instance.provider,
            'name': instance.display_name,
        })

    def perform_destroy(self, instance):
        org_id = instance.organisation_id
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'integration_delete',
            'provider': instance.provider,
            'name': instance.display_name,
        })
        instance.delete()
        IntegrationRegistry.clear_cache(org_id=org_id)

    # ------------------------------------------------------------------
    # Custom actions
    # ------------------------------------------------------------------

    @action(detail=True, methods=['post'], url_path='health-check')
    def health_check(self, request, pk=None):
        """
        Run health checks on the integration's configured providers.

        Checks log and/or metric provider depending on capabilities.
        """
        integration = self.get_object()

        # Short-circuit for demo-seeded integrations. The stored
        # credential is a sentinel placeholder and the host doesn't
        # exist — hitting the real adapter would just error, and we
        # don't want the demo box making outbound requests to
        # fabricated hostnames anyway.
        from .serializers import _DEMO_PLACEHOLDER
        if integration.get_password() == _DEMO_PLACEHOLDER:
            results = [{
                'provider': integration.provider,
                'provider_type': cap,
                'healthy': True,
                'message': 'OK (demo)',
            } for cap in (integration.capabilities or [])]
            ObservabilityIntegration.objects.filter(pk=integration.pk).update(
                last_health_check=timezone.now(),
                last_health_status=True,
            )
            return Response({'integrations': results, 'demo': True})

        results = []

        for cap in integration.capabilities:
            try:
                if cap == 'logs' and integration.log_adapter_class:
                    provider = IntegrationRegistry.get_log_provider(
                        integration.log_adapter_class,
                        integration.get_config(),
                        org_id=integration.organisation_id,
                    )
                    healthy = provider.health_check()
                    results.append({
                        'provider': type(provider).__name__,
                        'provider_type': 'log',
                        'healthy': healthy,
                        'message': 'OK' if healthy else 'Health check failed',
                    })
                elif cap == 'metrics' and integration.metric_adapter_class:
                    provider = IntegrationRegistry.get_metric_provider(
                        integration.metric_adapter_class,
                        integration.get_config(),
                        org_id=integration.organisation_id,
                    )
                    healthy = provider.health_check()
                    results.append({
                        'provider': type(provider).__name__,
                        'provider_type': 'metric',
                        'healthy': healthy,
                        'message': 'OK' if healthy else 'Health check failed',
                    })
            except Exception as exc:
                logger.error('Health check error for %s/%s: %s', integration.provider, cap, exc)
                results.append({
                    'provider': integration.provider,
                    'provider_type': cap,
                    'healthy': False,
                    'message': str(exc),
                })

        # Persist health status
        all_healthy = all(r['healthy'] for r in results) if results else False
        ObservabilityIntegration.objects.filter(pk=integration.pk).update(
            last_health_check=timezone.now(),
            last_health_status=all_healthy,
        )

        return Response({'integrations': results})

    @action(detail=True, methods=['get'], url_path='ingest-health')
    def ingest_health(self, request, pk=None):
        """Sample recent records + report canonical-field / alias presence.

        Answer the "am I tagging my logs / metrics correctly?" question
        without opening a Kibana / Grafana / Datadog console. Reports:

          * Which SerOps canonical fields (``service_name``,
            ``project_name``, ``environment``, ``log_level``,
            ``organisation_name``) are present in the last N records.
          * Which industry-standard aliases (Datadog USM ``service``/``env``,
            OpenTelemetry ``service.name``, Kubernetes ``app``, ...) are
            covering the gap when canonical is missing.
          * Warnings for records that lack ALL known aliases (those
            won't participate in filtered analysis).

        Query params:
          * ``minutes`` — sample window (1-1440, default 60)
          * ``limit``   — max records to sample (10-1000, default 100)

        Read-only. Sample size + window are clamped server-side to
        prevent DoS against the user's own provider. Returns only
        field NAME counts — never log values or PII.

        The result should NEVER include provider credentials — this
        is asserted by the ``ingest_health_never_leaks_credentials``
        test in ``integrations/tests/test_health.py``.
        """
        integration = self.get_object()

        try:
            minutes = int(request.query_params.get('minutes', 60))
            limit = int(request.query_params.get('limit', 100))
        except (TypeError, ValueError):
            return Response(
                {'error': 'minutes and limit must be integers'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Short-circuit for demo integrations so we don't try to reach
        # placeholder hostnames from the demo box.
        from .serializers import _DEMO_PLACEHOLDER
        if integration.get_password() == _DEMO_PLACEHOLDER:
            from datetime import datetime, timezone as _tz
            return Response({
                'integration_id': integration.id,
                'integration_name': integration.display_name,
                'provider': integration.provider,
                'provider_type': 'logs' if 'logs' in (integration.capabilities or []) else 'metrics',
                'sample_size': 0,
                'sample_window_minutes': minutes,
                'sampled_at': datetime.now(_tz.utc).isoformat(),
                'fields': [],
                'warnings': [],
                'recommendations': [
                    'Demo integration — real ingest health requires a live provider.',
                ],
                'demo': True,
                'error': None,
            })

        report = collect_ingest_health(
            integration,
            sample_size=limit,
            sample_window_minutes=minutes,
        )
        return Response(report.to_dict())

    @action(detail=False, methods=['get'], url_path='providers')
    def available_providers(self, request):
        """List all available provider types with their capabilities."""
        providers = []
        for code, display_name in ObservabilityIntegration.PROVIDER_CHOICES:
            providers.append({
                'code': code,
                'name': display_name,
                'capabilities': _available_capabilities(code),
            })
        return Response(providers)


class ClusterViewSet(viewsets.ModelViewSet):
    """
    CRUD for Kubernetes / VM clusters (Item #17).

    Endpoints (under /integrations/clusters/):
        GET    /                — list clusters for user's org
        POST   /                — create cluster (admin only)
        GET    /{id}/           — detail
        PATCH  /{id}/           — update (admin only)
        DELETE /{id}/           — delete (admin only). Integrations
                                  attached lose their cluster (SET_NULL)
                                  and become unscoped.

    Reads: any authenticated org member.
    Writes: admins only — cluster changes affect prompt scoping and
    integration routing, so we lock them down like other Settings
    surfaces.
    """

    serializer_class = ClusterSerializer

    def get_permissions(self):
        # Reads (list, retrieve, workloads) are open to any
        # authenticated org member — they need this to filter
        # the dashboard / picker. Writes stay admin-only.
        if self.action in ('list', 'retrieve', 'workloads'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminRole()]

    def get_queryset(self):
        user = self.request.user
        org = getattr(user, 'organisation', None)
        if org is None:
            return Cluster.objects.none()
        return Cluster.objects.filter(organisation=org).order_by('name')

    def perform_create(self, serializer):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError('User must belong to an organisation.')
        # Enforce unique name per org here as well as at DB level so we
        # return a clean 400 instead of an IntegrityError.
        name = serializer.validated_data.get('name', '')
        if Cluster.objects.filter(organisation=org, name=name).exists():
            from rest_framework import serializers as drf_serializers
            raise drf_serializers.ValidationError({
                'name': f"A cluster named '{name}' already exists for this org."
            })
        instance = serializer.save(organisation=org)
        # Clear cached adapters — cluster-aware lookups depend on
        # ObservabilityIntegration.cluster FK.
        IntegrationRegistry.clear_cache(org_id=org.id)
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'cluster_create',
            'name': instance.name,
            'provider': instance.provider,
        })

    def perform_update(self, serializer):
        instance = serializer.save()
        org = getattr(self.request.user, 'organisation', None)
        if org:
            IntegrationRegistry.clear_cache(org_id=org.id)
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'cluster_update',
            'name': instance.name,
        })

    def perform_destroy(self, instance):
        org_id = instance.organisation_id
        name = instance.name
        log_action(self.request, 'SETTINGS_CHANGE', {
            'setting': 'cluster_delete',
            'name': name,
        })
        instance.delete()
        IntegrationRegistry.clear_cache(org_id=org_id)

    @action(detail=True, methods=['get'], url_path='workloads')
    def workloads(self, request, pk=None):
        """
        Return the projects (and their services) assigned to this cluster.

        Powers the Workload view — a per-cluster breakdown of what
        SerOps is watching. Read-only, any authenticated org member.

        Shape::

            {
                "cluster": {"id": 1, "name": "prod-eks", ...},
                "projects": [
                    {"id": 5, "name": "checkout",
                     "services": [{"id": 12, "name": "api", "service_type": "application"}, ...]},
                    ...
                ]
            }
        """
        cluster = self.get_object()   # already org-scoped by get_queryset
        from Projects.models import Project
        projects = (
            Project.objects.filter(cluster=cluster)
            .prefetch_related('services')
            .order_by('name')
        )
        return Response({
            'cluster': ClusterSerializer(cluster).data,
            'projects': [
                {
                    'id': p.id,
                    'name': p.name,
                    'description': (p.description or '')[:200],
                    'services': [
                        {
                            'id': s.id,
                            'name': s.name or '',
                            'service_type': s.service_type,
                            'subtype': s.subtype or '',
                        }
                        for s in p.services.all()
                    ],
                }
                for p in projects
            ],
        })
