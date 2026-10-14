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

SSO_UNAVAILABLE = "SSO is not available for this account."


def _sso_settings_for(org_id):
    """The org's settings when OIDC sign-in is switched on, else None."""
    return SecuritySettings.objects.filter(
        organisation_id=org_id, sso_enabled=True, sso_provider='oidc',
    ).first()


def _sso_service(sec_settings):
    return SSOService(
        client_id=sec_settings.sso_client_id,
        client_secret=sec_settings.get_client_secret(),
        discovery_url=sec_settings.sso_discovery_url,
        redirect_uri=f"{settings.API_URL}/auth/sso/callback",
    )


class SSOConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.organisation:
            return Response({"error": "User does not belong to an organization"}, status=400)

        # A new organisation has no row yet; the Security page loads this
        # alongside /data/settings/security/, which creates it, so a plain
        # get() 404'd on first visit.
        sec_settings, _ = SecuritySettings.objects.get_or_create(organisation=user.organisation)
        return Response({
            "sso_enabled": sec_settings.sso_enabled,
            "sso_provider": sec_settings.sso_provider,  # 'oidc' or 'none'
            "sso_client_id": sec_settings.sso_client_id,
            "sso_discovery_url": sec_settings.sso_discovery_url,
            "sso_client_secret_configured": bool(sec_settings.sso_client_secret_encrypted),
            # What the admin registers at the identity provider.
            "sso_redirect_uri": f"{settings.API_URL}/auth/sso/callback",
        })

    @require_role('admin')
    def put(self, request):
        user = request.user
        if not user.organisation:
            return Response({"error": "User does not belong to an organization"}, status=400)

        data = request.data
        provider = data.get('sso_provider')
        if provider is not None and provider not in dict(SecuritySettings.SSO_TYPES):
            return Response({"error": "sso_provider must be 'oidc' or 'none'"}, status=400)

        sec_settings, _ = SecuritySettings.objects.get_or_create(organisation=user.organisation)
        sec_settings.sso_enabled = data.get('sso_enabled', sec_settings.sso_enabled)
        sec_settings.sso_provider = provider or sec_settings.sso_provider
        if sec_settings.sso_provider == 'oidc':
            sec_settings.sso_client_id = data.get('sso_client_id', sec_settings.sso_client_id)
            sec_settings.sso_discovery_url = data.get('sso_discovery_url', sec_settings.sso_discovery_url)
            # Only update secret if provided
            if data.get('sso_client_secret'):
                sec_settings.set_client_secret(data['sso_client_secret'])
        else:
            sec_settings.sso_enabled = False
        sec_settings.save()
        return Response({"message": "SSO configuration updated"})


class SSOInitView(APIView):
    """Start an OIDC sign-in for the organisation that owns ``email``.

    Every way of not getting an auth URL (unknown email, no organisation,
    SSO off, a demo account) gets the same 400, so this public endpoint
    does not reveal who has an account, and internal errors stay in the log.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_sso_init'

    def post(self, request):
        from .views import DEMO_ONLY_RESPONSE, demo_only_login
        if demo_only_login():
            return Response(DEMO_ONLY_RESPONSE, status=status.HTTP_403_FORBIDDEN)

        email = (request.data.get('email') or '').strip()
        if not email:
            return Response({"error": "Email is required"}, status=400)

        unavailable = Response({"error": SSO_UNAVAILABLE}, status=400)
        user = User.objects.filter(email__iexact=email, is_active=True, is_demo=False).first()
        if not user or not user.organisation_id:
            return unavailable
        sec_settings = _sso_settings_for(user.organisation_id)
        if not sec_settings:
            return unavailable

        try:
            state = signing.dumps({'org_id': user.organisation_id})
            auth_url, _ = _sso_service(sec_settings).get_authorization_url(state=state)
        except Exception:
            logger.exception("SSO init failed for org %s", user.organisation_id)
            return Response(
                {"error": "Could not reach the identity provider. Ask your administrator to check the SSO settings."},
                status=502,
            )
        return Response({"auth_url": auth_url})


class SSOCallbackView(APIView):
    """The identity provider redirects the browser here after sign-in.

    Failures send the browser back to the login page with ``?sso=failed``
    rather than a JSON error page. Only accounts of the organisation that
    started the flow can sign in: an IdP configured by one organisation
    must never be able to sign in as a member of another.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from .views import demo_only_login
        frontend_url = _validated_frontend_url()
        failed = redirect(f"{frontend_url}/login?sso=failed")

        code = request.query_params.get('code')
        state = request.query_params.get('state')
        if demo_only_login() or not code or not state:
            return failed

        try:
            org_id = signing.loads(state, max_age=600).get('org_id')
        except signing.BadSignature:
            return failed
        sec_settings = _sso_settings_for(org_id)
        if not sec_settings:
            return failed

        try:
            sso = _sso_service(sec_settings)
            user_info = sso.get_user_info(sso.exchange_code_for_token(code))
        except Exception:
            logger.exception("SSO callback: token exchange failed for org %s", org_id)
            return failed

        email = (user_info.get('email') or '').strip()
        if not email or user_info.get('email_verified') is False:
            logger.warning("SSO callback: IdP returned no verified email for org %s", org_id)
            return failed

        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create(
                email=email,
                username=email.split('@')[0][:20],
                first_name=user_info.get('given_name', ''),
                last_name=user_info.get('family_name', ''),
                organisation_id=org_id,
                role='viewer',  # Default role for new SSO users
                is_active=True,
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
        elif user.organisation_id != org_id or user.is_demo or not user.is_active:
            logger.warning("SSO callback: refused user %s for org %s", user.pk, org_id)
            return failed

        # Create a short-lived Knox token for this session.
        _, token = AuthToken.objects.create(user)

        # Hand the token off to the frontend via an HttpOnly cookie
        # rather than a URL query param. Tokens in URLs leak through
        # browser history, referrer headers, and proxy/server logs.
        # The frontend exchanges this cookie for a usable token via
        # POST /api/auth/sso/exchange (see SSOExchangeView below).
        response = redirect(f"{frontend_url}/auth/callback")
        response.set_cookie(
            key=SSO_HANDOFF_COOKIE,
            value=token,
            max_age=SSO_HANDOFF_TTL_SECONDS,
            httponly=True,
            # Secure on every https install. Browsers drop Secure cookies
            # over plain http, which made SSO impossible on an http lab
            # install (the Helm chart's default, without TLS).
            secure=request.is_secure() or (settings.API_URL or '').startswith('https://'),
            samesite='Lax',
            path='/api/auth/sso/exchange',
        )
        return response


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
