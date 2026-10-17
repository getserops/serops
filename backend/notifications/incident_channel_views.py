"""CRUD + test-send API for IncidentNotificationChannel (Items #22/#23)."""

import logging

from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from Middlewares.rbac import IsAdminRole
from .models import IncidentNotificationChannel

logger = logging.getLogger(__name__)


class IncidentNotificationChannelSerializer(serializers.ModelSerializer):
    kind_display = serializers.CharField(source='get_kind_display', read_only=True)
    # Write-only secret fields — accept plaintext on create/update,
    # store encrypted, never return on reads.
    webhook_url_input = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True,
    )
    api_key_input = serializers.CharField(
        write_only=True, required=False, allow_blank=True, allow_null=True,
    )
    has_webhook_url = serializers.SerializerMethodField()
    has_api_key = serializers.SerializerMethodField()

    class Meta:
        model = IncidentNotificationChannel
        fields = [
            'id', 'name', 'kind', 'kind_display',
            'webhook_url_input', 'has_webhook_url',
            'api_key_input', 'has_api_key',
            'extra_config',
            'trigger_events', 'min_severity',
            'is_active',
            'last_sent_at', 'last_error',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'id', 'kind_display', 'last_sent_at', 'last_error',
            'created_at', 'updated_at',
            'has_webhook_url', 'has_api_key',
        ]

    def get_has_webhook_url(self, obj):
        return bool(obj.webhook_url)

    def get_has_api_key(self, obj):
        return bool(obj.api_key)

    def validate_kind(self, value):
        valid = {k for k, _ in IncidentNotificationChannel.KIND_CHOICES}
        if value not in valid:
            raise serializers.ValidationError(
                f'Invalid kind {value!r}. Allowed: {sorted(valid)}'
            )
        return value

    def validate_trigger_events(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError('trigger_events must be a list.')
        valid = {t for t, _ in IncidentNotificationChannel.TRIGGER_CHOICES}
        bad = [t for t in value if t not in valid]
        if bad:
            raise serializers.ValidationError(
                f'Unknown trigger_events: {bad}. Allowed: {sorted(valid)}'
            )
        return value

    def validate(self, attrs):
        kind = attrs.get('kind', getattr(self.instance, 'kind', None))
        # Slack + Teams need a webhook URL; PD + OG need an API key. Only
        # enforce on create — on update, the existing value may be used.
        if self.instance is None:
            if kind in ('slack', 'teams') and not attrs.get('webhook_url_input'):
                raise serializers.ValidationError(
                    {'webhook_url_input': f'Required for kind={kind}'}
                )
            if kind in ('pagerduty', 'opsgenie') and not attrs.get('api_key_input'):
                raise serializers.ValidationError(
                    {'api_key_input': f'Required for kind={kind}'}
                )
        return attrs

    def validate_webhook_url_input(self, value):
        """Slack/Teams webhooks must be public https URLs: an org admin
        must not be able to make the server POST to internal services or
        the cloud metadata endpoint (SSRF)."""
        if value:
            from Utils.url_validator import validate_public_url
            try:
                validate_public_url(value)
            except ValueError as exc:
                raise serializers.ValidationError(str(exc))
        return value

    def create(self, validated_data):
        webhook_url = validated_data.pop('webhook_url_input', None)
        api_key = validated_data.pop('api_key_input', None)
        instance = super().create(validated_data)
        if webhook_url is not None:
            instance.set_webhook_url(webhook_url)
        if api_key is not None:
            instance.set_api_key(api_key)
        if webhook_url is not None or api_key is not None:
            instance.save(update_fields=['webhook_url', 'api_key'])
        return instance

    def update(self, instance, validated_data):
        webhook_url = validated_data.pop('webhook_url_input', None)
        api_key = validated_data.pop('api_key_input', None)
        instance = super().update(instance, validated_data)
        changed = []
        if webhook_url is not None:
            instance.set_webhook_url(webhook_url)
            changed.append('webhook_url')
        if api_key is not None:
            instance.set_api_key(api_key)
            changed.append('api_key')
        if changed:
            instance.save(update_fields=changed)
        return instance


class IncidentNotificationChannelViewSet(viewsets.ModelViewSet):
    """
    /api/notification/incident-channels/ — org-scoped CRUD.

    Reads: authenticated. Writes: admin (matches Settings pattern).
    """

    serializer_class = IncidentNotificationChannelSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminRole()]

    def get_queryset(self):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            return IncidentNotificationChannel.objects.none()
        return IncidentNotificationChannel.objects.filter(organisation=org)

    def perform_create(self, serializer):
        org = getattr(self.request.user, 'organisation', None)
        if org is None:
            raise serializers.ValidationError('User must belong to an organisation.')
        serializer.save(organisation=org)

    @action(detail=True, methods=['post'], url_path='test-send')
    def test_send(self, request, pk=None):
        """Send a synthetic test message. Useful for verifying the URL/secret."""
        channel = self.get_object()
        from notifications.senders import SENDER_BY_KIND
        sender = SENDER_BY_KIND.get(channel.kind)
        if sender is None:
            return Response(
                {'error': f'No sender registered for kind={channel.kind}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload = {
            'title': 'SerOps test message',
            'batch_id': 'test',
            'project_name': 'test-project',
            'environment': 'production',
            'top_severity': 'INFO',
            'issue_count': 0,
            'root_cause': 'This is a test message from SerOps. Ignore.',
            'recommendation': 'If you see this, your channel is wired correctly.',
            'incident_url': '',
        }
        ok, msg = sender(channel, payload)
        from django.utils import timezone
        if ok:
            channel.last_sent_at = timezone.now()
            channel.last_error = ''
        else:
            channel.last_error = msg[:1000]
        channel.save(update_fields=['last_sent_at', 'last_error'])
        return Response({'ok': ok, 'message': msg}, status=200)
