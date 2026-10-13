"""PR-N phase 2 (2026-09-26): CRUD for ``NotificationRoutingRule``.

Grafana / Alertmanager-style route table. Each rule declares a
matcher (severity + environments + services + event_types) and a
set of target channels. Dispatcher walks active rules → union of
matching targets → dedup → send.
"""
from __future__ import annotations
import logging

from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated

from Middlewares.rbac import IsAdminRole
from .models import IncidentNotificationChannel, NotificationRoutingRule

logger = logging.getLogger(__name__)


class NotificationRoutingRuleSerializer(serializers.ModelSerializer):
    """Full CRUD serializer. Targets by PK, filtered to the caller's org."""

    target_ids = serializers.PrimaryKeyRelatedField(
        source='targets', many=True,
        queryset=IncidentNotificationChannel.objects.none(),  # narrowed below
        required=False,
    )

    class Meta:
        model = NotificationRoutingRule
        fields = [
            'id', 'name', 'is_active',
            'min_severity', 'environments', 'services', 'event_types',
            'target_ids',
            'suppress_for_minutes', 'escalate_after_minutes', 'priority',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        org = getattr(getattr(request, 'user', None), 'organisation', None)
        if org is not None:
            self.fields['target_ids'].child_relation.queryset = (
                IncidentNotificationChannel.objects.filter(organisation=org)
            )

    def validate_min_severity(self, value):
        if not value:
            return ''
        allowed = set(IncidentNotificationChannel.SEVERITY_ORDER) | {''}
        if value.upper() not in allowed:
            raise serializers.ValidationError(
                f'Invalid severity {value!r}. Allowed: {sorted(allowed)}'
            )
        return value.upper()

    def _validate_list_of_strings(self, value, field_name):
        if not isinstance(value, list):
            raise serializers.ValidationError(f'{field_name} must be a list')
        for item in value:
            if not isinstance(item, str):
                raise serializers.ValidationError(
                    f'{field_name} entries must be strings',
                )
        return value

    def validate_environments(self, value):
        return self._validate_list_of_strings(value, 'environments')

    def validate_services(self, value):
        return self._validate_list_of_strings(value, 'services')

    def validate_event_types(self, value):
        value = self._validate_list_of_strings(value, 'event_types')
        allowed = {k for k, _ in IncidentNotificationChannel.TRIGGER_CHOICES}
        for item in value:
            if item not in allowed:
                raise serializers.ValidationError(
                    f'Unknown event type {item!r}. Allowed: {sorted(allowed)}',
                )
        return value


class NotificationRoutingRuleViewSet(viewsets.ModelViewSet):
    """org-scoped CRUD; admin only for writes."""
    serializer_class = NotificationRoutingRuleSerializer
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get_queryset(self):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            return NotificationRoutingRule.objects.none()
        return (
            NotificationRoutingRule.objects
            .filter(organisation=org)
            .prefetch_related('targets')
            .order_by('priority', 'name')
        )

    def perform_create(self, serializer):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            raise serializers.ValidationError('User has no organisation')
        serializer.save(organisation=org)
