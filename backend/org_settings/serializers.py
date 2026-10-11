"""
Serializers for Organisation Settings API.
"""

from rest_framework import serializers
from .models import (
    AIModelProvider,
    OrganisationAISettings,
    OrganisationAPIKey,
    SentinelConfig,
)


class AIModelProviderSerializer(serializers.ModelSerializer):
    """Serializer for AI model providers."""
    
    class Meta:
        model = AIModelProvider
        fields = [
            'id',
            'name',
            'display_name',
            'is_active',
            'requires_api_key',
            'default_model',
            'adapter_class',
            'rate_limits',
            'circuit_config',
            'validation_config',
            'is_system',
            'env_key_name',
        ]
        read_only_fields = ['id']
        extra_kwargs = {
            'name': {'validators': []}
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Robustly remove unique validator from name field to allow updates
        # This handles edge cases where extra_kwargs might be overridden
        name_field = self.fields.get('name')
        if name_field:
            name_field.validators = []

    def validate_name(self, value):
        """Check for unique name, excluding current instance on update."""
        from .models import AIModelProvider
        qs = AIModelProvider.objects.filter(name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("AI Model Provider with this Name already exists.")
        return value


class OrganisationAISettingsSerializer(serializers.ModelSerializer):
    """Serializer for organisation AI settings."""
    
    default_provider_name = serializers.CharField(
        source='default_provider.name',
        read_only=True
    )
    default_provider_display = serializers.CharField(
        source='default_provider.display_name',
        read_only=True
    )
    fallback_provider_name = serializers.CharField(
        source='fallback_provider.name',
        read_only=True,
        allow_null=True
    )
    fallback_provider_display = serializers.CharField(
        source='fallback_provider.display_name',
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = OrganisationAISettings
        fields = [
            'id',
            'default_provider',
            'default_provider_name',
            'default_provider_display',
            'fallback_provider',
            'fallback_provider_name',
            'fallback_provider_display',
            'use_custom_keys',
            'monthly_budget_usd',
            'budget_warn_pct',
            'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']

    def validate(self, attrs):
        default_id = attrs.get('default_provider')
        fallback_id = attrs.get('fallback_provider')
        # Resolve from instance when not in payload (partial update)
        if default_id is None and self.instance:
            default_id = self.instance.default_provider_id
        if fallback_id is None and self.instance:
            fallback_id = self.instance.fallback_provider_id
        # Resolve PK from model instances
        default_pk = getattr(default_id, 'pk', default_id)
        fallback_pk = getattr(fallback_id, 'pk', fallback_id)
        if default_pk and fallback_pk and default_pk == fallback_pk:
            raise serializers.ValidationError(
                {'fallback_provider': 'Fallback provider cannot be the same as the default provider.'}
            )
        return attrs


class OrganisationAPIKeySerializer(serializers.ModelSerializer):
    """Serializer for organisation API keys."""
    
    provider_name = serializers.CharField(
        source='provider.name',
        read_only=True
    )
    provider_display = serializers.CharField(
        source='provider.display_name',
        read_only=True
    )
    masked_key = serializers.SerializerMethodField()
    
    class Meta:
        model = OrganisationAPIKey
        fields = [
            'id',
            'provider',
            'provider_name',
            'provider_display',
            'masked_key',
            'base_url',
            'is_active',
            'last_tested_at',
            'last_test_success',
            'updated_at'
        ]
        read_only_fields = ['id', 'masked_key', 'last_tested_at', 'last_test_success', 'updated_at']
    
    def get_masked_key(self, obj):
        return obj.get_masked_key()


class APIKeyCreateUpdateSerializer(serializers.Serializer):
    """Serializer for creating/updating API keys."""
    
    provider_id = serializers.IntegerField()
    api_key = serializers.CharField(max_length=500)
    base_url = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    
    def validate_api_key(self, value):
        if len(value) < 20:
            raise serializers.ValidationError("API key is too short (minimum 20 characters).")
        return value


class WebhookTestSerializer(serializers.Serializer):
    """Serializer for webhook test requests.

    ``webhook_url`` is routed through :func:`Utils.url_validator.validate_public_url`
    to reject any URL that resolves to a private / loopback / link-local
    address. Otherwise an authenticated admin could use the test endpoint
    to probe internal infrastructure (AWS metadata, localhost admin,
    coworker services on the same VPC) — a classic SSRF against an
    otherwise-authenticated feature.
    """

    webhook_type = serializers.ChoiceField(choices=['slack', 'teams'])
    webhook_url = serializers.URLField()

    def validate_webhook_url(self, value):
        from Utils.url_validator import validate_public_url
        try:
            return validate_public_url(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))


class AIConnectionTestSerializer(serializers.Serializer):
    """Serializer for AI connection test requests."""
    
    provider_name = serializers.CharField(max_length=100)
    api_key = serializers.CharField(max_length=500, required=False)


class IssueSettingsSerializer(serializers.ModelSerializer):
    """Serializer for issue deduplication and memory settings."""

    class Meta:
        from .models import IssueSettings
        model = IssueSettings
        fields = [
            'id',
            'dedup_enabled',
            'dedup_window_days',
            'default_mute_duration_days',
            'auto_resolve_enabled',
            'auto_resolve_after_days',
            # Past-incident memory injection (Data/memory.py)
            'memory_enabled',
            'memory_window_days',
            'memory_max_items',
            'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']

    def validate_memory_window_days(self, value):
        if value < 1 or value > 730:
            raise serializers.ValidationError(
                'memory_window_days must be between 1 and 730 (two years).'
            )
        return value

    def validate_memory_max_items(self, value):
        if value < 0 or value > 10:
            raise serializers.ValidationError(
                'memory_max_items must be between 0 and 10 (token budget control).'
            )
        return value


class SentinelConfigSerializer(serializers.ModelSerializer):
    """Serializer for per-org Sentinel configuration."""

    class Meta:
        model = SentinelConfig
        fields = [
            'id', 'active_mode',
            'error_spike_multiplier', 'z_score_threshold',
            'max_quiet_batches', 'updated_at'
        ]
        read_only_fields = ['id', 'updated_at']


# SystemMailSettingsSerializer removed 2026-09-01 alongside the
# SystemMailSettings model + views. SMTP is now env-only.
