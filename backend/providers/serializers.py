"""
Serializers for Provider Integrations.

Handles secure credential input (write-only) and safe output (masked tokens).
"""

from rest_framework import serializers
from .models import ProviderIntegration


class ProviderIntegrationSerializer(serializers.ModelSerializer):
    """
    Serializer for ProviderIntegration model.
    
    Security:
    - access_token is write-only (never returned in responses)
    - credentials field encrypts on save
    - Sensitive data is masked in responses
    """
    
    # Write-only field for accepting tokens
    access_token = serializers.CharField(
        write_only=True, 
        required=False, 
        allow_blank=True,
        help_text='API access token (write-only, encrypted at rest)'
    )
    
    # Read-only computed fields
    is_verified = serializers.BooleanField(read_only=True)
    needs_verification = serializers.BooleanField(read_only=True)
    display_url = serializers.CharField(read_only=True)
    token_masked = serializers.SerializerMethodField()
    
    class Meta:
        model = ProviderIntegration
        fields = [
            'id',
            'name',
            'provider_type',
            'category',
            'base_url',
            'capabilities',
            'verification_status',
            'last_verified_at',
            'verification_error',
            'token_expires_at',
            'is_active',
            'created_at',
            'updated_at',
            # Write-only
            'access_token',
            # Read-only computed
            'is_verified',
            'needs_verification',
            'display_url',
            'token_masked',
        ]
        read_only_fields = [
            'id',
            'verification_status',
            'last_verified_at',
            'verification_error',
            'created_at',
            'updated_at',
        ]
    
    def validate_base_url(self, value):
        """Self-hosted servers on private networks are allowed; cloud
        metadata endpoints are not (the server calls this URL)."""
        if value:
            from Utils.url_validator import validate_outbound_url
            try:
                validate_outbound_url(value)
            except ValueError as e:
                raise serializers.ValidationError(str(e))
        return value

    # Credential fields that are not the secret: who the token belongs to
    # (Jenkins and Bitbucket authenticate as username + token) and the Azure
    # DevOps organization. Stored encrypted with the token.
    _CREDENTIAL_EXTRAS = ('username', 'email', 'organization', 'workspace')
    _TOKEN_KEYS = ('access_token', 'token', 'api_token', 'api_key', 'app_password')

    def to_internal_value(self, data):
        """Accept the token as ``credentials: {access_token: ...}`` too.

        The token field is ``access_token``; a ``credentials`` object (what
        the model stores, and what API clients reach for) used to be dropped
        without a word, so the integration was saved with no token and every
        call failed "Authentication failed" (phase 3 client test C1).

        The rest of ``credentials`` (username, organization) is kept with the
        token: the settings page sends the Jenkins and Bitbucket username
        there, and dropping it meant those integrations could never
        authenticate (phase 3 client test C3)."""
        creds = data.get('credentials') if hasattr(data, 'get') else None
        self._credential_extras = {}
        if creds is not None:
            if not isinstance(creds, dict):
                raise serializers.ValidationError({'credentials': 'Must be an object.'})
            token = next((creds.get(k) for k in self._TOKEN_KEYS
                          if isinstance(creds.get(k), str) and creds.get(k).strip()), None)
            extras = {k: str(creds[k]).strip()[:255] for k in self._CREDENTIAL_EXTRAS
                      if isinstance(creds.get(k), (str, int)) and str(creds[k]).strip()}
            if not token and not extras and not data.get('access_token'):
                raise serializers.ValidationError(
                    {'credentials': 'Send the token as access_token (or credentials.access_token).'})
            if token and data.get('access_token') and data.get('access_token') != token:
                raise serializers.ValidationError(
                    {'credentials': 'access_token and credentials.access_token differ; send one.'})
            data = {k: v for k, v in data.items() if k != 'credentials'}
            if token:
                data['access_token'] = token
            self._credential_extras = extras
        return super().to_internal_value(data)

    def _store_credentials(self, instance, access_token):
        """Save the token and the non-secret credential fields together,
        keeping whichever of the two this request did not change."""
        extras = getattr(self, '_credential_extras', {}) or {}
        if not access_token and not extras:
            return False
        current = {}
        if instance.credentials:
            try:
                current = instance.get_credentials() or {}
            except Exception:
                current = {}
        merged = {k: v for k, v in current.items() if k != '_encrypted'}
        merged.update(extras)
        if access_token:
            for k in self._TOKEN_KEYS:
                merged.pop(k, None)
            merged['access_token'] = access_token
        instance.set_credentials(merged)
        return True

    def get_token_masked(self, obj) -> str:
        """Return masked version of token for display (no decryption needed)."""
        return obj.token_hint or ''
    
    def create(self, validated_data):
        """Create integration with encrypted credentials."""
        access_token = validated_data.pop('access_token', None)
        
        # Get organisation from request context
        request = self.context.get('request')
        if request and hasattr(request.user, 'organisation'):
            validated_data['organisation'] = request.user.organisation
            validated_data['created_by'] = request.user
        
        # Set default capabilities based on provider type
        if 'capabilities' not in validated_data or not validated_data['capabilities']:
            integration = ProviderIntegration(**validated_data)
            validated_data['capabilities'] = integration.get_default_capabilities()
        
        instance = super().create(validated_data)
        
        # Set credentials securely
        if self._store_credentials(instance, access_token):
            instance.save(update_fields=['credentials', 'token_hint'])
        
        return instance
    
    def update(self, instance, validated_data):
        """Update integration, handling credential changes securely."""
        access_token = validated_data.pop('access_token', None)
        
        instance = super().update(instance, validated_data)
        
        # Update credentials if a new token or username was provided; the
        # other half is kept.
        if self._store_credentials(instance, access_token):
            instance.verification_status = 'pending'  # Require re-verification
            instance.save(update_fields=['credentials', 'token_hint', 'verification_status'])
        
        return instance


class ProviderIntegrationListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing integrations.
    Used in dropdowns and quick lists.
    """
    is_verified = serializers.BooleanField(read_only=True)
    display_url = serializers.CharField(read_only=True)
    
    class Meta:
        model = ProviderIntegration
        fields = [
            'id',
            'name',
            'provider_type',
            'category',
            'display_url',
            'is_verified',
            'is_active',
            # The integrations page shows "added 3 days ago"; without this
            # it showed "Unknown" and a tooltip reading "Invalid Date".
            'created_at',
        ]


class VerifyIntegrationSerializer(serializers.Serializer):
    """Serializer for integration verification response."""
    success = serializers.BooleanField()
    message = serializers.CharField()
    user_info = serializers.DictField(required=False)


class DiscoveredRepoSerializer(serializers.Serializer):
    """Serializer for discovered repository."""
    id = serializers.CharField(help_text='Provider-specific repo ID')
    name = serializers.CharField()
    full_name = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_null=True)
    url = serializers.URLField(required=False)
    default_branch = serializers.CharField(required=False, default='main')
    is_private = serializers.BooleanField(required=False, default=False)
    last_activity_at = serializers.DateTimeField(required=False, allow_null=True)

