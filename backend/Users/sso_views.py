from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from .models import User, SecuritySettings
from .services.sso import SSOService
from knox.models import AuthToken
from django.shortcuts import redirect
from django.core import signing
from Users.permissions import require_role
import logging

logger = logging.getLogger(__name__)

class SSOConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.organisation:
            return Response({"error": "User does not belong to an organization"}, status=400)
            
        # A new organisation has no row yet; the Security page loads this
        # alongside /data/settings/security/, which creates it, so a plain
        # get() 404'd on first visit.
        settings, _ = SecuritySettings.objects.get_or_create(organisation=user.organisation)
        return Response({
            "sso_enabled": settings.sso_enabled,
            "sso_provider": settings.sso_provider, # 'oidc' or 'saml' or 'none'
            
            # OIDC
            "sso_client_id": settings.sso_client_id,
            "sso_discovery_url": settings.sso_discovery_url,
            "sso_realm": settings.sso_realm,
            "sso_client_secret_configured": bool(settings.sso_client_secret_encrypted),
            
            # SAML
            "saml_entity_id": settings.saml_entity_id,
            "saml_sso_url": settings.saml_sso_url,
            "saml_x509_cert": settings.saml_x509_cert,
        })

    @require_role('admin')
    def put(self, request):
        user = request.user
        if not user.organisation:
            return Response({"error": "User does not belong to an organization"}, status=400)

        data = request.data
        settings, created = SecuritySettings.objects.get_or_create(organisation=user.organisation)
        
        settings.sso_enabled = data.get('sso_enabled', settings.sso_enabled)
        settings.sso_provider = data.get('sso_provider', settings.sso_provider)
        
        # OIDC
        if settings.sso_provider == 'oidc':
            settings.sso_client_id = data.get('sso_client_id', settings.sso_client_id)
            settings.sso_discovery_url = data.get('sso_discovery_url', settings.sso_discovery_url)
            settings.sso_realm = data.get('sso_realm', settings.sso_realm)
            # Only update secret if provided
            if data.get('sso_client_secret'):
                settings.set_client_secret(data['sso_client_secret'])
        
        # SAML
        if settings.sso_provider == 'saml':
            settings.saml_entity_id = data.get('saml_entity_id', settings.saml_entity_id)
            settings.saml_sso_url = data.get('saml_sso_url', settings.saml_sso_url)
            settings.saml_x509_cert = data.get('saml_x509_cert', settings.saml_x509_cert)
            
        settings.save()
        return Response({"message": "SSO configuration updated"})


class SSOInitView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_sso_init'

    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=400)
            
        try:
            user = User.objects.get(email=email)
            if not user.organisation:
                return Response({"error": "User has no organization"}, status=400)
                
            sec_settings = SecuritySettings.objects.get(organisation=user.organisation)
            
            if not sec_settings.sso_enabled or sec_settings.sso_provider == 'none':
                return Response({"error": "SSO not enabled for this organization"}, status=400)
            
            # --- SAML FLOW ---
            if sec_settings.sso_provider == 'saml':
                return Response({
                    "error": "SAML is not supported. Please configure OIDC instead.",
                    "hint": "All major identity providers (Keycloak, Okta, Azure AD, Google) support OIDC. "
                            "Change your SSO provider to 'oidc' in Settings > Security.",
                }, status=status.HTTP_400_BAD_REQUEST)

            # --- OIDC FLOW ---
            if sec_settings.sso_provider == 'oidc' or sec_settings.sso_provider in ['okta', 'azure_ad', 'google', 'keycloak']: # Backwards compat
                # Initialize Service
                sso = SSOService(
                    client_id=sec_settings.sso_client_id,
                    client_secret=sec_settings.get_client_secret(),
                    discovery_url=sec_settings.sso_discovery_url,
                    redirect_uri=f"{settings.API_URL}/auth/sso/callback"
                )
                
                # Generate secure state with Org ID
                state_data = {'org_id': user.organisation.id}
                state = signing.dumps(state_data)
                
                auth_url, _ = sso.get_authorization_url(state=state)
                
                return Response({"auth_url": auth_url})
            
            return Response({"error": "Unknown SSO Provider Type"}, status=400)
            
        except User.DoesNotExist:
            return Response({"error": "User not found"}, status=404)
        except Exception as e:
            logger.error(f"SSO Init Error: {e}")
            return Response({"error": str(e)}, status=500)


class SSOCallbackView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        code = request.query_params.get('code')
        state = request.query_params.get('state')
        
        if not code or not state:
             return Response({"error": "Missing code or state"}, status=400)
             
        try:
            # Decode state to get Org ID
            state_data = signing.loads(state, max_age=3600) # Expire in 1 hour
            org_id = state_data.get('org_id')
            
            # Fetch Org Settings
            sec_settings = SecuritySettings.objects.get(organisation_id=org_id)
            
            sso = SSOService(
                client_id=sec_settings.sso_client_id,
                client_secret=sec_settings.get_client_secret(),
                discovery_url=sec_settings.sso_discovery_url,
                redirect_uri=f"{settings.API_URL}/auth/sso/callback"
            )
            
            # Exchange Code
            token = sso.exchange_code_for_token(code)
            
            # Get User Info
            user_info = sso.get_user_info(token)
            email = user_info.get('email')
            
            if not email:
                return Response({"error": "No email returned from IdP"}, status=400)
            
            # Find or Create User
            user, created = User.objects.get_or_create(email=email, defaults={
                'username': email.split('@')[0],
                'first_name': user_info.get('given_name', ''),
                'last_name': user_info.get('family_name', ''),
                'organisation_id': org_id,
                'role': 'viewer', # Default role for new SSO users
                'is_active': True 
            })
            
            # Create a short-lived Knox token for this session.
            _, token = AuthToken.objects.create(user)

            # Hand the token off to the frontend via an HttpOnly cookie
            # rather than a URL query param. Tokens in URLs leak through
            # browser history, referrer headers, and proxy/server logs.
            # The frontend exchanges this cookie for a usable token via
            # POST /api/auth/sso/exchange (see SSOExchangeView below).
            frontend_url = _validated_frontend_url()
            response = redirect(f"{frontend_url}/auth/callback")
            response.set_cookie(
                key=SSO_HANDOFF_COOKIE,
                value=token,
                max_age=SSO_HANDOFF_TTL_SECONDS,
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',
                path='/api/auth/sso/exchange',
            )
            return response

        except signing.BadSignature:
            return Response({"error": "Invalid state parameter"}, status=400)
        except Exception as e:
            logger.error(f"SSO Callback Error: {e}")
            return Response({"error": f"Login failed: {str(e)}"}, status=400)


# =============================================================================
# SSO handoff helpers
# =============================================================================
# After the IdP redirects the user back to /api/auth/sso/callback we set
# the Knox token in a HttpOnly cookie scoped to the exchange endpoint.
# The frontend immediately POSTs to /api/auth/sso/exchange, which reads
# the cookie, clears it, and returns the token in the response body for
# normal localStorage / Authorization header use.
SSO_HANDOFF_COOKIE = 'serops_sso_handoff'
SSO_HANDOFF_TTL_SECONDS = 120  # short window — exchange happens immediately


def _validated_frontend_url() -> str:
    """Return a frontend URL from the CORS allowlist, never user-controlled."""
    allowed = getattr(settings, 'CORS_ALLOWED_ORIGINS', None) or []
    if allowed:
        return allowed[0]
    react_url = getattr(settings, 'REACT_URL', None)
    if react_url:
        return react_url
    return 'http://localhost:3003'


class SSOExchangeView(APIView):
    """Exchange the short-lived handoff cookie for a usable Knox token.

    The frontend's /auth/callback page calls this immediately after the
    IdP redirect. The handoff cookie is HttpOnly and scoped to this path
    so it never reaches application JS and never appears in a URL.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        token = request.COOKIES.get(SSO_HANDOFF_COOKIE)
        if not token:
            return Response(
                {"error": "Missing or expired SSO handoff"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Look the token up so we can return the user's identity, then
        # rotate the handoff cookie out regardless of outcome.
        from knox.settings import CONSTANTS
        token_obj = AuthToken.objects.filter(
            token_key=token[:CONSTANTS.TOKEN_KEY_LENGTH]
        ).first()
        if not token_obj:
            response = Response(
                {"error": "Invalid SSO handoff"},
                status=status.HTTP_400_BAD_REQUEST,
            )
            response.delete_cookie(SSO_HANDOFF_COOKIE, path='/api/auth/sso/exchange')
            return response

        user = token_obj.user
        response = Response({
            'token': token,
            'user': {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'role': user.role,
                'organisation_id': user.organisation_id,
            },
        })
        response.delete_cookie(SSO_HANDOFF_COOKIE, path='/api/auth/sso/exchange')
        return response
