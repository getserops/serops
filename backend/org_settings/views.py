"""
API Views for Organisation Settings.
"""

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import api_view, permission_classes
from django.utils import timezone
import logging

from Middlewares.rbac import IsAdminRole
from Data.audit import log_action, log_settings_change
from .models import (
    AIModelProvider,
    OrganisationAISettings,
    OrganisationAPIKey,
    IssueSettings,
    SentinelConfig,
)
from .serializers import (
    AIModelProviderSerializer,
    OrganisationAISettingsSerializer,
    OrganisationAPIKeySerializer,
    APIKeyCreateUpdateSerializer,
    WebhookTestSerializer,
    AIConnectionTestSerializer,
    IssueSettingsSerializer,
    SentinelConfigSerializer,
)
from .webhooks import send_test_slack_webhook, send_test_teams_webhook

logger = logging.getLogger(__name__)


# PR-N phase 2 (2026-09-26): ``NotificationSettingsView`` retired.
# Delivery targets now live at
# ``/api/notifications/incident-channels/`` and routing at
# ``/api/notifications/routing-rules/`` — see notifications app.


class TestWebhookView(APIView):
    """
    API endpoint to test webhook configurations.
    POST: Send a test message to Slack or Teams webhook
    """
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    def post(self, request):
        """Test a webhook by sending a test message."""
        serializer = WebhookTestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        webhook_type = serializer.validated_data['webhook_type']
        webhook_url = serializer.validated_data['webhook_url']
        
        if webhook_type == 'slack':
            success, error = send_test_slack_webhook(webhook_url)
        else:
            success, error = send_test_teams_webhook(webhook_url)
        
        if success:
            log_action(request, 'NOTIFICATION_TEST', {'type': webhook_type})
            return Response({
                'success': True,
                'message': f'{webhook_type.capitalize()} webhook test successful!'
            })
        else:
            return Response({
                'success': False,
                'error': error
            }, status=status.HTTP_400_BAD_REQUEST)


class AIModelProvidersView(APIView):
    """
    API endpoint to list available AI model providers.
    GET: List all active AI providers
    """
    
    def get_permissions(self):
        """Allow read for authenticated, write for admin only."""
        if self.request.method == 'GET':
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsAdminRole()]

    def get(self, request):
        """Get list of available AI providers."""
        providers = AIModelProvider.objects.all() # Show all to admin? or just active?
        # If admin, show all. If user, show active?
        # For now, show all as this is mainly for settings management
        serializer = AIModelProviderSerializer(providers, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Register a new AI provider."""
        serializer = AIModelProviderSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            log_action(request, 'SETTINGS_CHANGE', {
                'setting': 'ai_provider_create',
                'provider': serializer.data.get('name'),
            })
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AIModelProviderDetailView(APIView):
    """
    API endpoint for managing a specific AI provider.
    GET: Retrieve details
    PATCH: Update config
    DELETE: Remove provider
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get_object(self, pk):
        try:
            return AIModelProvider.objects.get(pk=pk)
        except AIModelProvider.DoesNotExist:
            return None

    def get(self, request, pk):
        provider = self.get_object(pk)
        if not provider:
            return Response({'error': 'Provider not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = AIModelProviderSerializer(provider)
        return Response(serializer.data)

    def patch(self, request, pk):
        provider = self.get_object(pk)
        if not provider:
            return Response({'error': 'Provider not found'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AIModelProviderSerializer(provider, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            log_action(request, 'SETTINGS_CHANGE', {
                'setting': 'ai_provider_update',
                'provider': provider.name,
            })
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        """Allow full update via PUT (mapped to partial update for convenience)."""
        return self.patch(request, pk)

    def delete(self, request, pk):
        provider = self.get_object(pk)
        if not provider:
            return Response({'error': 'Provider not found'}, status=status.HTTP_404_NOT_FOUND)

        if provider.is_system:
            return Response(
                {'error': f'Cannot delete system provider "{provider.display_name}". Deactivate it instead.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        log_action(request, 'SETTINGS_CHANGE', {
            'setting': 'ai_provider_delete',
            'provider': provider.name,
        })
        provider.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AvailableModelsView(APIView):
    """
    API endpoint to get models available for re-analysis.
    Returns only models with active API keys for the user's organization.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get list of models available for the current organisation."""
        from ai_model.ai_service import get_api_key_for_org

        user_org = getattr(request.user, 'organisation', None)

        # Get all active providers (system-wide active)
        active_providers = AIModelProvider.objects.filter(is_active=True)

        # Only include providers the org can actually use (has API key or env var)
        models = []
        for p in active_providers:
            api_key, _, _ = get_api_key_for_org(user_org, p.name)
            if api_key:
                models.append({'id': p.name, 'name': p.display_name})

        return Response({'models': models})


class AISettingsView(APIView):
    """
    API endpoint for managing AI settings.
    GET: Retrieve current AI settings
    PUT: Update AI settings
    """
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    def get(self, request):
        """Get AI settings for current organisation.

        Auto-creates ``OrganisationAISettings`` with ``default_provider=NULL``
        for orgs that haven't picked one yet. Previously this view
        silently defaulted to Gemini on first read — that reintroduced
        the presumed-provider anti-pattern the Day 1 rework killed
        (see ai_service.py note on why silent defaults are wrong).
        The onboarding wizard's AI provider step is now the only
        legitimate place a default provider gets set.
        """
        try:
            settings_obj, _ = OrganisationAISettings.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = OrganisationAISettingsSerializer(settings_obj)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching AI settings: {e}")
            return Response(
                {'error': 'Failed to fetch AI settings'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def put(self, request):
        """Update AI settings for current organisation."""
        try:
            settings, created = OrganisationAISettings.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = OrganisationAISettingsSerializer(
                settings,
                data=request.data,
                partial=True
            )
            if serializer.is_valid():
                serializer.save()
                
                # Log AI settings changes
                changes = {}
                for field in ('default_provider', 'fallback_provider', 'use_custom_keys'):
                    if field in request.data:
                        changes[field] = request.data[field]
                if changes:
                    log_action(request, 'AI_MODEL_CHANGE', changes)

                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating AI settings: {e}")
            return Response(
                {'error': 'Failed to update AI settings'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AIBudgetStatusView(APIView):
    """
    GET /api/settings/ai/budget/  — Q3.3 read-only spend snapshot.

    Returns::

        {
            "monthly_budget_usd": "500.00" | null,
            "current_spend_usd": "234.57",
            "remaining_usd": "265.43" | null,   // null when no cap
            "warn_threshold_pct": 80,
            "is_warning": true | false,
            "is_exceeded": true | false,
            "month_start_utc": "2026-09-01T00:00:00Z"
        }

    Read-safe for any authenticated org member — spend data is
    non-sensitive within an org. Writes go through the standard
    AISettingsView PUT.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ai_model.budget import BudgetTracker
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return Response({'error': 'No organisation'}, status=400)
        check = BudgetTracker.check_budget(org)
        return Response({
            'monthly_budget_usd': str(check.budget) if check.budget is not None else None,
            'current_spend_usd': str(check.current),
            'remaining_usd': str(check.remaining) if check.remaining is not None else None,
            'warn_threshold_pct': (
                BudgetTracker._settings_for(org).budget_warn_pct
                if BudgetTracker._settings_for(org) else 80
            ),
            'is_warning': BudgetTracker.is_warning(org),
            'is_exceeded': not check.ok,
            'month_start_utc': BudgetTracker._month_start().isoformat(),
        })


class OllamaProbeView(APIView):
    """
    POST /api/settings/ai/ollama/probe/  — Q4.1 pre-flight check.

    Body: ``{"base_url": "http://localhost:11434/v1/"}``
    Returns::

        {
            "reachable": true,
            "models": ["llama3.1:8b", "qwen3:8b", ...],
            "error": null
        }

    Used by the Settings UI to validate an Ollama endpoint before
    the admin saves the AI provider config. Wraps HTTP with a tight
    5-second timeout — never blocks the request thread for long.

    Security:
    * Admin-only. Reaching arbitrary URLs from the backend is a
      minor SSRF surface; scoping to admins limits blast radius.
    * URL scheme restricted to http/https; localhost + internal-net
      URLs are the point of Ollama, so they're allowed.
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request):
        import requests
        from Utils.url_validator import validate_internal_url_no_metadata

        base_url = str(request.data.get('base_url') or '').strip()
        if not base_url:
            return Response(
                {'reachable': False, 'models': [], 'error': 'base_url is required'},
                status=400,
            )
        # BE-P1-06 (audit 2026-09-05): scheme check alone let an admin
        # point at http://169.254.169.254/ (cloud metadata IMDS) and
        # exfiltrate short-lived cloud credentials via SSRF. Full
        # public-URL enforcement would break legitimate self-hosted
        # Ollama at http://localhost:11434, so we use the weaker
        # helper that allows private ranges but blocks the metadata
        # endpoints attackers actually want.
        try:
            validate_internal_url_no_metadata(base_url)
        except ValueError as exc:
            return Response(
                {'reachable': False, 'models': [], 'error': str(exc)},
                status=400,
            )
        url = base_url.rstrip('/') + '/models'
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json() or {}
            models = [
                str(m.get('id') or m.get('name') or '')
                for m in (data.get('data') or data.get('models') or [])
                if isinstance(m, dict)
            ]
            models = [m for m in models if m]
            return Response({
                'reachable': True,
                'models': models,
                'error': None,
            })
        except requests.exceptions.RequestException as exc:
            return Response({
                'reachable': False,
                'models': [],
                'error': f'Could not reach Ollama at {url}: {exc}',
            })
        except (ValueError, TypeError) as exc:
            return Response({
                'reachable': False,
                'models': [],
                'error': f'Malformed response from {url}: {exc}',
            })


class APIKeysView(APIView):
    """
    API endpoint for managing API keys.
    GET: List all API keys (masked)
    POST: Add or update an API key
    DELETE: Remove an API key
    """
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    def get(self, request):
        """Get all API keys for current organisation (masked)."""
        api_keys = OrganisationAPIKey.objects.filter(
            organisation=request.user.organisation
        ).select_related('provider')
        serializer = OrganisationAPIKeySerializer(api_keys, many=True)
        return Response(serializer.data)
    
    def post(self, request):
        """Add or update an API key."""
        serializer = APIKeyCreateUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            provider = AIModelProvider.objects.get(
                id=serializer.validated_data['provider_id']
            )
        except AIModelProvider.DoesNotExist:
            return Response(
                {'error': 'Provider not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Encrypt the API key before storing
        from .encryption import encrypt_api_key
        encrypted_key = encrypt_api_key(serializer.validated_data['api_key'])
        
        # Build defaults dict
        defaults = {
            'api_key': encrypted_key,
            'is_active': True
        }
        
        # Add base_url if provided
        if 'base_url' in serializer.validated_data and serializer.validated_data['base_url']:
            defaults['base_url'] = serializer.validated_data['base_url']
        
        api_key, created = OrganisationAPIKey.objects.update_or_create(
            organisation=request.user.organisation,
            provider=provider,
            defaults=defaults
        )

        log_action(request, 'SETTINGS_CHANGE', {
            'setting': 'api_key_save',
            'provider': provider.name,
            'action': 'created' if created else 'updated',
        })

        response_serializer = OrganisationAPIKeySerializer(api_key)
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
    
    def delete(self, request, provider_id=None):
        """Remove an API key."""
        if not provider_id:
            return Response(
                {'error': 'Provider ID required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            api_key = OrganisationAPIKey.objects.get(
                organisation=request.user.organisation,
                provider_id=provider_id
            )
            log_action(request, 'SETTINGS_CHANGE', {
                'setting': 'api_key_delete',
                'provider': api_key.provider.name,
            })
            api_key.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except OrganisationAPIKey.DoesNotExist:
            return Response(
                {'error': 'API key not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class TestAIConnectionView(APIView):
    """
    API endpoint to test AI provider connections.
    POST: Test connection to an AI provider
    """
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    def post(self, request):
        """Test connection to an AI provider."""
        serializer = AIConnectionTestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        provider_name = serializer.validated_data['provider_name']
        custom_api_key = serializer.validated_data.get('api_key')
        
        try:
            # Import here to avoid circular imports
            from ai_model.ai_service import generate_text_unified, get_api_key_for_org
            
            # Fetch the actual API key configured for this organisation
            api_key, base_url, extra_config = get_api_key_for_org(request.user.organisation, provider_name)
            source = "database"

            # Use the custom key passed in request (if any) or the stored one
            if custom_api_key:
                api_key = custom_api_key
                source = "request_param"
            
            logger.debug("Testing AI connection: provider=%s, source=%s", provider_name, source)

            if not api_key:
                 return Response({
                    'success': False,
                    'error': f'No API key found for {provider_name}. Please save the key first.'
                }, status=status.HTTP_400_BAD_REQUEST)

            test_prompt = "Say 'Connection successful' in exactly those words."
            
            response, error, _, _ = generate_text_unified(
                test_prompt,
                provider=provider_name,
                api_key=api_key,
                base_url=base_url,
                extra_config=extra_config,
            )
            
            if error:
                # Update test status if API key exists
                self._update_test_status(request.user.organisation, provider_name, False)
                return Response({
                    'success': False,
                    'error': str(error)
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Update test status
            self._update_test_status(request.user.organisation, provider_name, True)
            
            return Response({
                'success': True,
                'message': f'{provider_name.capitalize()} connection successful!',
                'response_preview': response[:100] if response else None
            })
            
        except Exception as e:
            logger.error(f"Error testing AI connection: {e}")
            self._update_test_status(request.user.organisation, provider_name, False)
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _update_test_status(self, organisation, provider_name, success):
        """Update the test status for an API key."""
        try:
            provider = AIModelProvider.objects.get(name=provider_name)
            api_key = OrganisationAPIKey.objects.filter(
                organisation=organisation,
                provider=provider
            ).first()
            if api_key:
                api_key.last_tested_at = timezone.now()
                api_key.last_test_success = success
                api_key.save()
        except (AIModelProvider.DoesNotExist, Exception) as e:
            logger.warning(f"Could not update test status: {e}")


class IssueSettingsView(APIView):
    """
    API endpoint for managing issue deduplication settings.
    GET: Retrieve current issue settings
    PUT: Update issue settings
    """
    permission_classes = [IsAuthenticated, IsAdminRole]
    
    def get(self, request):
        """Get issue settings for current organisation."""
        try:
            settings, created = IssueSettings.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = IssueSettingsSerializer(settings)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching issue settings: {e}")
            return Response(
                {'error': 'Failed to fetch issue settings'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def put(self, request):
        """Update issue settings for current organisation."""
        try:
            settings, created = IssueSettings.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = IssueSettingsSerializer(
                settings,
                data=request.data,
                partial=True
            )
            if serializer.is_valid():
                serializer.save()
                log_settings_change(request, 'issue_settings',
                                    {}, serializer.validated_data)
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating issue settings: {e}")
            return Response(
                {'error': 'Failed to update issue settings'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SentinelConfigView(APIView):
    """
    API endpoint for managing Sentinel configuration.
    GET: Retrieve current sentinel config (creates defaults on first access)
    PUT: Update sentinel config
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def get(self, request):
        try:
            config, created = SentinelConfig.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = SentinelConfigSerializer(config)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error fetching sentinel config: {e}")
            return Response(
                {'error': 'Failed to fetch sentinel config'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def put(self, request):
        try:
            config, created = SentinelConfig.objects.get_or_create(
                organisation=request.user.organisation
            )
            serializer = SentinelConfigSerializer(
                config,
                data=request.data,
                partial=True
            )
            if serializer.is_valid():
                serializer.save()
                log_settings_change(request, 'sentinel_config',
                                    {}, serializer.validated_data)
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error updating sentinel config: {e}")
            return Response(
                {'error': 'Failed to update sentinel config'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# NOTE: SystemMailSettingsView and TestMailConnectionView were removed
# 2026-09-01. SMTP is now env-only (Grafana model). Configure via .env
# and restart. Verify with `python manage.py check_smtp <recipient>`.
