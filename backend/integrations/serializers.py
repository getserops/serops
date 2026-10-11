"""
DRF Serializers for Observability Integration Management.
"""

from rest_framework import serializers

from .models import (
    Cluster,
    IntegrationScope,
    ObservabilityIntegration,
    ADAPTER_MAP,
    _available_capabilities,
)


class IntegrationScopeSerializer(serializers.ModelSerializer):
    """Nested serializer for the four scope dimensions (Batch 53).

    ``cluster`` lives on the parent ObservabilityIntegration and is
    mirrored automatically by the model — we only surface the three
    free-text dimensions here so writers don't try to set two clusters.
    """

    class Meta:
        model = IntegrationScope
        fields = ['environment', 'region', 'namespace']


# Mirrors the constant in Data.management.commands.seed_demo_org — kept
# duplicated to avoid a runtime dep on a management command from a
# serializer. Any value that equals this literal is treated as a demo
# placeholder and never rendered to the client.
_DEMO_PLACEHOLDER = 'SEED_DEMO_PLACEHOLDER_NOT_A_REAL_SECRET'
_DEMO_MASK = '•••• (demo)'


def _scrub_extra_config(cfg):
    """Replace any placeholder-valued key so the demo sentinel never leaks."""
    if not isinstance(cfg, dict):
        return cfg
    return {k: (_DEMO_MASK if v == _DEMO_PLACEHOLDER else v) for k, v in cfg.items()}


class ObservabilityIntegrationSerializer(serializers.ModelSerializer):
    """Full CRUD serializer for ObservabilityIntegration."""

    provider_display = serializers.CharField(
        source='get_provider_display', read_only=True
    )
    available_capabilities = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()
    cluster_name = serializers.CharField(source='cluster.name', read_only=True, default=None)
    priority_tier_display = serializers.CharField(
        source='get_priority_tier_display', read_only=True,
    )
    # Nested scope — a write-through OneToOne that always exists (signal
    # auto-creates on integration save). Missing keys on the request leave
    # existing values intact so a partial PATCH doesn't clear scope.
    scope = IntegrationScopeSerializer(required=False)

    class Meta:
        model = ObservabilityIntegration
        fields = [
            'id',
            'provider',
            'provider_display',
            'display_name',
            'capabilities',
            'available_capabilities',
            'is_active',
            'cluster',
            'cluster_name',
            'topology_mode',
            'priority_tier',
            'priority_tier_display',
            'scope',
            'host',
            'username',
            'password',
            'has_password',
            'extra_config',
            'timeout_seconds',
            'max_retries',
            'rate_limit_per_minute',
            'last_health_check',
            'last_health_status',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'log_adapter_class',
            'metric_adapter_class',
            'last_health_check',
            'last_health_status',
            'created_at',
            'updated_at',
        ]
        extra_kwargs = {
            'password': {'write_only': True, 'required': False},
        }

    def get_available_capabilities(self, obj):
        return _available_capabilities(obj.provider)

    def get_has_password(self, obj):
        return bool(obj.password)

    def validate_provider(self, value):
        if value not in ADAPTER_MAP:
            raise serializers.ValidationError(
                f"Unsupported provider: {value}. "
                f"Choices: {list(ADAPTER_MAP.keys())}"
            )
        return value

    def validate_capabilities(self, value):
        if not isinstance(value, list) or not value:
            raise serializers.ValidationError(
                "capabilities must be a non-empty list, e.g. ['logs'] or ['logs','metrics']."
            )
        for cap in value:
            if cap not in ('logs', 'metrics'):
                raise serializers.ValidationError(
                    f"Invalid capability '{cap}'. Allowed: 'logs', 'metrics'."
                )
        return value

    def validate_cluster(self, value):
        """Cluster (if provided) must belong to the caller's org."""
        if value is None:
            return value
        request = self.context.get('request')
        org = getattr(request.user, 'organisation', None) if request else None
        if org and value.organisation_id != org.id:
            # Same error whether it's cross-org or wrong-org — no leak.
            raise serializers.ValidationError('Cluster not found for your organisation.')
        return value

    def validate(self, attrs):
        provider = attrs.get('provider', getattr(self.instance, 'provider', None))
        capabilities = attrs.get(
            'capabilities', getattr(self.instance, 'capabilities', [])
        )
        # Cluster on the incoming payload (or existing instance's cluster).
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))

        # Ensure requested capabilities are valid for this provider
        available = _available_capabilities(provider)
        for cap in capabilities:
            if cap not in available:
                raise serializers.ValidationError(
                    {
                        'capabilities': (
                            f"Provider '{provider}' does not support '{cap}'. "
                            f"Available: {available}"
                        )
                    }
                )

        # Tier-sliced uniqueness — (org, provider, cluster, tier) since
        # Batch 48. Users register the same-cluster same-provider row
        # once per tier (primary + fallback + tertiary). Short-circuit
        # early with a readable error; the DB constraint is still the
        # ultimate authority (see ObservabilityIntegration.Meta).
        if not self.instance and provider:
            request = self.context.get('request')
            org = getattr(request.user, 'organisation', None) if request else None
            tier = attrs.get('priority_tier', 'primary')
            if org:
                dup_qs = ObservabilityIntegration.objects.filter(
                    organisation=org, provider=provider, cluster=cluster,
                    priority_tier=tier,
                )
                if dup_qs.exists():
                    scope = f"cluster '{cluster.name}'" if cluster else 'the unscoped default'
                    raise serializers.ValidationError({
                        'provider': (
                            f"A {tier} integration for '{provider}' already exists on {scope}. "
                            f"Use a different priority tier to add a second one."
                        )
                    })

        # Namespace-requires-cluster invariant on the nested scope.
        scope_payload = attrs.get('scope')
        if scope_payload and scope_payload.get('namespace'):
            if cluster is None:
                raise serializers.ValidationError({
                    'scope': {
                        'namespace': 'Namespace requires a cluster to be selected.',
                    }
                })

        return attrs

    def create(self, validated_data):
        raw_password = validated_data.pop('password', '')
        scope_data = validated_data.pop('scope', None)
        instance = super().create(validated_data)
        if raw_password:
            instance.set_password(raw_password)
            instance.save(update_fields=['password'])
        if scope_data:
            # Signal auto-created an empty IntegrationScope on integration
            # save — hydrate it with the user's env/region/ns choices.
            self._apply_scope(instance, scope_data)
        return instance

    def update(self, instance, validated_data):
        raw_password = validated_data.pop('password', None)
        scope_data = validated_data.pop('scope', None)
        instance = super().update(instance, validated_data)
        if raw_password:
            instance.set_password(raw_password)
            instance.save(update_fields=['password'])
        if scope_data is not None:
            self._apply_scope(instance, scope_data)
        return instance

    def _apply_scope(self, instance, scope_data):
        # OneToOne with primary_key=integration — get_or_create is safe.
        # ``cluster`` on IntegrationScope is not settable via API; the
        # model save() on ObservabilityIntegration mirrors it from the
        # parent cluster. Keep this in sync explicitly here so a POST
        # that only sets env/region/ns still ends up with cluster mirrored.
        scope, _ = IntegrationScope.objects.get_or_create(integration=instance)
        for field in ('environment', 'region', 'namespace'):
            if field in scope_data:
                setattr(scope, field, scope_data[field] or '')
        scope.cluster = instance.cluster
        scope.save()

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['extra_config'] = _scrub_extra_config(data.get('extra_config'))
        # Empty nested serializer default → surface a stable {} shape
        # instead of None so the frontend doesn't crash on `.environment`.
        if data.get('scope') is None:
            data['scope'] = {'environment': '', 'region': '', 'namespace': ''}
        return data


class ObservabilityIntegrationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""

    provider_display = serializers.CharField(
        source='get_provider_display', read_only=True
    )
    has_password = serializers.SerializerMethodField()

    class Meta:
        model = ObservabilityIntegration
        fields = [
            'id',
            'provider',
            'provider_display',
            'display_name',
            'capabilities',
            'is_active',
            'topology_mode',
            'priority_tier',
            'host',
            'username',
            'has_password',
            'extra_config',
            'last_health_check',
            'last_health_status',
        ]

    def get_has_password(self, obj):
        return bool(obj.password)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['extra_config'] = _scrub_extra_config(data.get('extra_config'))
        return data


class IntegrationHealthSerializer(serializers.Serializer):
    """Read-only serializer for health check responses."""

    provider = serializers.CharField()
    provider_type = serializers.CharField()
    healthy = serializers.BooleanField()
    message = serializers.CharField()


class AvailableProvidersSerializer(serializers.Serializer):
    """Serializer for the available providers endpoint."""

    code = serializers.CharField()
    name = serializers.CharField()
    capabilities = serializers.ListField(child=serializers.CharField())


class ClusterSerializer(serializers.ModelSerializer):
    """CRUD serializer for :class:`Cluster` (Item #17)."""

    provider_display = serializers.CharField(source='get_provider_display', read_only=True)
    # Convenience count so the UI can show "3 integrations attached".
    integration_count = serializers.SerializerMethodField()

    class Meta:
        model = Cluster
        fields = [
            'id', 'name', 'description', 'provider', 'provider_display',
            'region', 'kubernetes_context', 'is_active',
            'integration_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_integration_count(self, obj):
        return obj.observability_integrations.count()

    def validate_name(self, value):
        # Names appear in UI dropdowns + prompts; strip and require non-empty.
        value = (value or '').strip()
        if not value:
            raise serializers.ValidationError('name is required')
        if len(value) > 100:
            raise serializers.ValidationError('name must be 100 characters or fewer')
        return value
