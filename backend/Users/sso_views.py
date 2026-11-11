from Middlewares.rbac import ROLE_PERMISSIONS, Requires, can_grant
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.throttling import ScopedRateThrottle
from django.conf import settings
from .models import User, SecuritySettings
from .services.sso import SSOService
from . import sso_roles
from Utils import edition
from Data.audit import log_action
from Middlewares.rbac import can_manage_shared_settings, role_key
from knox.models import AuthToken
from django.shortcuts import redirect
from django.core import signing
from django.utils.crypto import constant_time_compare
import logging
import re
import secrets
from urllib.parse import urlsplit

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
        extra_scopes=sec_settings.sso_extra_scopes,
    )


SSO_CALLBACK_PATH = '/api/auth/sso/callback'
SSO_FLOW_COOKIE = 'serops_sso_flow'
SSO_FLOW_SALT = 'serops.sso-flow'
SSO_FLOW_TTL_SECONDS = 600


def _cookie_secure(request):
    # Secure on every https install. Browsers drop Secure cookies over plain
    # http, which made SSO impossible on an http lab install (the Helm
    # chart's default, without TLS).
    return request.is_secure() or (settings.API_URL or '').startswith('https://')


def _email_verified(user_info, discovery_url):
    """Whether the identity provider vouches for the email it returned."""
    claim = user_info.get('email_verified')
    if claim is None:
        return (urlsplit(discovery_url or '').hostname or '').lower() in settings.SSO_TRUST_MISSING_EMAIL_VERIFIED
    # Some providers (AWS Cognito) send the string "true".
    return claim is True or str(claim).lower() == 'true'


def _email_domain(email):
    return email.rsplit('@', 1)[-1].strip().lower() if '@' in email else ''


def _settings_for_domain(email):
    """SSO settings of the organisation that lists the email's domain."""
    domain = _email_domain(email)
    if not domain:
        return None
    # Saving refuses a domain another organisation lists, but 1.2.6 allowed
    # it: a domain two organisations claim signs in nobody, since which one
    # a stranger belongs to cannot be guessed.
    matches = [sec for sec in SecuritySettings.objects.filter(sso_enabled=True, sso_provider='oidc')
               .exclude(sso_domains=[]) if domain in (sec.sso_domains or [])]
    return matches[0] if len(matches) == 1 else None


def _resolve_key(sec_settings, key):
    """(role, custom_role) for a rule's role key; (None, None) if it is gone."""
    from Middlewares.rbac import resolve_role_key
    try:
        return resolve_role_key(sec_settings.organisation, key)
    except ValueError:
        logger.error("SSO: role %r of org %s no longer exists", key, sec_settings.organisation_id)
        return None, None


def _would_remove_last_admin(user, new_role):
    return (user.role == 'admin' and new_role != 'admin' and not User.objects.filter(
        organisation_id=user.organisation_id, role='admin', is_active=True).exclude(pk=user.pk).exists())


class SSOConfigView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='settings.read', PUT='settings.manage')]

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
            "sso_groups_claim": sec_settings.sso_groups_claim,
            "sso_extra_scopes": sec_settings.sso_extra_scopes,
            "sso_role_mappings": sec_settings.sso_role_mappings,
            "sso_default_role": sec_settings.sso_default_role,
            "sso_sync_role": sec_settings.sso_sync_role,
            "sso_domains": sec_settings.sso_domains or [],
            "sso_team_mappings": sec_settings.sso_team_mappings,
            # Domains are install-wide (they route sign-ins to this
            # organisation), so on multi-organisation installs only
            # platform staff set them.
            "sso_domains_editable": can_manage_shared_settings(user),
            # What the admin registers at the identity provider.
            "sso_redirect_uri": f"{settings.API_URL}/auth/sso/callback",
        })

    def put(self, request):
        user = request.user
        if not user.organisation:
            return Response({"error": "User does not belong to an organization"}, status=400)

        data = request.data
        provider = data.get('sso_provider')
        if provider is not None and provider not in dict(SecuritySettings.SSO_TYPES):
            return Response({"error": "sso_provider must be 'oidc' or 'none'"}, status=400)

        sec_settings, _ = SecuritySettings.objects.get_or_create(organisation=user.organisation)
        # The identity provider decides who signs in as whom: whoever points
        # SSO at a provider of their own can assert any member's email. A
        # custom role with settings.manage could sign in as the admin this
        # way (review 2026-11-05), so changing it takes every permission an
        # admin holds.
        identity_fields = ('sso_enabled', 'sso_provider', 'sso_client_id', 'sso_discovery_url', 'sso_client_secret')
        changes_identity = any(
            key in data and (key == 'sso_client_secret' and data[key] or
                             key != 'sso_client_secret' and data[key] != getattr(sec_settings, key))
            for key in identity_fields)
        if changes_identity and not can_grant(user, ROLE_PERMISSIONS['admin']):
            return Response({"error": "Changing the identity provider needs every permission of an admin."},
                            status=403)
        errors = self._apply_role_settings(request, sec_settings, data)
        if errors:
            return Response({"error": "; ".join(errors), "errors": errors}, status=400)
        sec_settings.sso_enabled = data.get('sso_enabled', sec_settings.sso_enabled)
        sec_settings.sso_provider = provider or sec_settings.sso_provider
        if sec_settings.sso_provider == 'oidc':
            sec_settings.sso_client_id = data.get('sso_client_id', sec_settings.sso_client_id)
            discovery_url = data.get('sso_discovery_url', sec_settings.sso_discovery_url)
            if discovery_url and discovery_url != sec_settings.sso_discovery_url:
                # Fetched by the server on every SSO sign-in; it was saved
                # with no check at all (security review 2026-11, finding 3).
                from Utils.url_validator import validate_outbound_url
                try:
                    validate_outbound_url(discovery_url)
                except ValueError as exc:
                    return Response({"error": f"sso_discovery_url: {exc}"}, status=400)
            sec_settings.sso_discovery_url = discovery_url
            # Only update secret if provided
            if data.get('sso_client_secret'):
                sec_settings.set_client_secret(data['sso_client_secret'])
        else:
            sec_settings.sso_enabled = False
        sec_settings.save()
        return Response({"message": "SSO configuration updated"})

    @staticmethod
    def _apply_role_settings(request, sec, data):
        """Validate and set the group mapping fields present in ``data``."""
        org = request.user.organisation
        mappings = data.get('sso_role_mappings', sec.sso_role_mappings)
        default_role = data.get('sso_default_role', sec.sso_default_role)
        errors = sso_roles.validate_mappings(org, mappings, default_role)
        if not errors:
            # A rule hands its role to whoever is in the group: setting one
            # needs the permissions of that role (no escalation through SSO).
            from Middlewares.rbac import can_grant, key_permissions
            targets = {r['role'] for r in mappings} | ({default_role} - {sso_roles.DENY})
            if any(not can_grant(request.user, key_permissions(org, t)) for t in targets):
                errors.append('You can only map groups to roles whose permissions you hold')
            # A rule that hands out a custom role is Enterprise; rules already
            # saved keep working, and can be removed, without a license.
            current = {r.get('role') for r in sec.sso_role_mappings or []} | {sec.sso_default_role}
            new_custom = {t for t in targets if str(t).startswith('custom:')} - current
            if new_custom and not edition.has_feature('custom_roles'):
                errors.append(edition.license_error('custom_roles')['error'])
        if 'sso_groups_claim' in data:
            claim = str(data['sso_groups_claim'] or '').strip()
            if len(claim) > 255 or ' ' in claim:
                errors.append('sso_groups_claim must be a claim name or dotted path')
            sec.sso_groups_claim = claim or 'groups'
        if 'sso_extra_scopes' in data:
            scopes = ' '.join(str(data['sso_extra_scopes'] or '').split())
            if len(scopes) > 255:
                errors.append('sso_extra_scopes is too long')
            sec.sso_extra_scopes = scopes
        if 'sso_sync_role' in data:
            sec.sso_sync_role = bool(data['sso_sync_role'])
        if 'sso_domains' in data:
            try:
                domains = sso_roles.normalise_domains(data['sso_domains'])
            except ValueError as e:
                errors.append(str(e))
                domains = None
            if domains is not None and domains != (sec.sso_domains or []):
                if not can_manage_shared_settings(request.user):
                    errors.append('Only platform staff can set email domains on an install with several organisations')
                else:
                    taken = [d for d in domains for other in SecuritySettings.objects.exclude(pk=sec.pk)
                             if d in (other.sso_domains or [])]
                    if taken:
                        errors.append(f'Already used by another organisation: {", ".join(sorted(set(taken)))}')
                    else:
                        sec.sso_domains = domains
        if 'sso_team_mappings' in data:
            team_errors, teams = sso_roles.validate_team_mappings(org, data['sso_team_mappings'])
            errors += team_errors
            from Middlewares.project_access import can_manage_team
            if not team_errors and any(not can_manage_team(request.user, t) for t in teams):
                errors.append("You can only map groups to teams whose project access you hold")
            if not errors:
                sec.sso_team_mappings = [{'group': str(r['group']).strip(), 'team_id': r['team_id']}
                                         for r in data['sso_team_mappings']]
        if not errors:
            sec.sso_role_mappings = [{'group': str(r['group']).strip(), 'role': r['role']} for r in mappings]
            sec.sso_default_role = default_role
        return errors


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
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            if not user.is_active or user.is_demo or not user.organisation_id:
                return unavailable
            sec_settings = _sso_settings_for(user.organisation_id)
        else:
            # No account yet: an organisation that lists the email's domain
            # creates it at the first sign-in.
            sec_settings = _settings_for_domain(email)
        if not sec_settings:
            return unavailable
        org_id = sec_settings.organisation_id

        # A random value in the state makes each flow distinct; the cookie
        # below ties it, the nonce and the PKCE verifier to this browser.
        state = signing.dumps({'org_id': org_id, 'flow': secrets.token_urlsafe(16)})
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        try:
            auth_url, _ = _sso_service(sec_settings).get_authorization_url(
                state=state, nonce=nonce, code_verifier=code_verifier)
        except Exception:
            logger.exception("SSO init failed for org %s", sec_settings.organisation_id)
            return Response(
                {"error": "Could not reach the identity provider. Ask your administrator to check the SSO settings."},
                status=502,
            )
        response = Response({"auth_url": auth_url})
        response.set_cookie(
            key=SSO_FLOW_COOKIE,
            value=signing.dumps({'state': state, 'nonce': nonce, 'verifier': code_verifier}, salt=SSO_FLOW_SALT),
            max_age=SSO_FLOW_TTL_SECONDS,
            httponly=True,
            secure=_cookie_secure(request),
            samesite='Lax',  # Sent on the identity provider's redirect back.
            path=SSO_CALLBACK_PATH,
        )
        return response


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
        failed.delete_cookie(SSO_FLOW_COOKIE, path=SSO_CALLBACK_PATH)

        code = request.query_params.get('code')
        state = request.query_params.get('state')
        if demo_only_login() or not code or not state:
            return failed

        # The callback must land in the browser that started the flow, once.
        # Otherwise an attacker could get a victim to load the attacker's own
        # callback URL and sign the victim in to the attacker's account.
        try:
            flow = signing.loads(request.COOKIES.get(SSO_FLOW_COOKIE, ''), salt=SSO_FLOW_SALT,
                                 max_age=SSO_FLOW_TTL_SECONDS)
            org_id = signing.loads(state, max_age=SSO_FLOW_TTL_SECONDS).get('org_id')
        except signing.BadSignature:
            logger.warning("SSO callback: no valid flow cookie or state")
            return failed
        if not constant_time_compare(flow['state'], state):
            logger.warning("SSO callback: state does not match this browser's flow")
            return failed
        sec_settings = _sso_settings_for(org_id)
        if not sec_settings:
            return failed

        try:
            sso = _sso_service(sec_settings)
            token = sso.exchange_code_for_token(code, code_verifier=flow['verifier'])
            if not sso.id_token_matches(token, flow['nonce']):
                logger.warning("SSO callback: ID token does not match the flow for org %s", org_id)
                return failed
            user_info = sso.get_user_info(token)
        except Exception:
            logger.exception("SSO callback: token exchange failed for org %s", org_id)
            return failed

        email = (user_info.get('email') or '').strip()
        if not email or not _email_verified(user_info, sec_settings.sso_discovery_url):
            logger.warning("SSO callback: IdP returned no verified email for org %s", org_id)
            return failed

        # Groups may be in the userinfo response or only in the ID token
        # (Entra ID); userinfo wins where both have a claim.
        claims = {**sso_roles.id_token_claims(token), **user_info}
        groups = sso_roles.extract_groups(claims, sec_settings.sso_groups_claim)
        role = sso_roles.resolve_role(groups, sec_settings.sso_role_mappings, sec_settings.sso_default_role)

        user = User.objects.filter(email__iexact=email).first()
        if user is not None and (user.organisation_id != org_id or user.is_demo or not user.is_active):
            logger.warning("SSO callback: refused user %s for org %s", user.pk, org_id)
            return failed
        if role is None:
            logger.info("SSO callback: an email is in no mapped group of org %s", org_id)
            log_action(request, 'SSO_DENIED', {'email': email, 'groups': groups[:50]},
                       user=user, organisation=sec_settings.organisation)
            denied = redirect(f"{frontend_url}/login?sso=denied")
            denied.delete_cookie(SSO_FLOW_COOKIE, path=SSO_CALLBACK_PATH)
            return denied

        if user is None:
            if _email_domain(email) not in (sec_settings.sso_domains or []):
                logger.warning("SSO callback: no account for an email whose domain is not listed (org %s)", org_id)
                return failed
            new_role, custom_role = _resolve_key(sec_settings, role)
            if new_role is None:
                return failed
            user = User.objects.create(
                email=email,
                username=email.split('@')[0][:20],
                first_name=user_info.get('given_name', ''),
                last_name=user_info.get('family_name', ''),
                organisation_id=org_id,
                role=new_role,
                custom_role=custom_role,
                is_active=True,
            )
            user.set_unusable_password()
            user.save(update_fields=['password'])
            log_action(request, 'SSO_PROVISION', {'affected_user': email, 'role': role, 'groups': groups[:50]},
                       user=user, organisation=sec_settings.organisation)
        elif sec_settings.sso_sync_role and role_key(user) != role:
            new_role, custom_role = _resolve_key(sec_settings, role)
            if new_role is None:
                return failed
            if _would_remove_last_admin(user, new_role):
                logger.warning("SSO callback: kept %s as admin, the organisation's last one", user.pk)
            else:
                old_role = role_key(user)
                user.role, user.custom_role = new_role, custom_role
                user.save(update_fields=['role', 'custom_role'])
                log_action(request, 'TEAM_ROLE_CHANGE', {
                    'affected_user': user.email, 'role': role, 'old_role': old_role,
                    'source': 'sso', 'groups': groups[:50]}, user=user, organisation=sec_settings.organisation)

        added, removed = sso_roles.sync_teams(user, groups, sec_settings.sso_team_mappings)
        if added or removed:
            log_action(request, 'TEAM_UPDATE', {'affected_user': user.email, 'added_to': added,
                                                'removed_from': removed, 'source': 'sso'},
                       user=user, organisation=sec_settings.organisation)

        # Create a short-lived Knox token for this session.
        _, token = AuthToken.objects.create(user)

        # Hand the token off to the frontend via an HttpOnly cookie
        # rather than a URL query param. Tokens in URLs leak through
        # browser history, referrer headers, and proxy/server logs.
        # The frontend exchanges this cookie for a usable token via
        # POST /api/auth/sso/exchange (see SSOExchangeView below).
        response = redirect(f"{frontend_url}/auth/callback")
        response.delete_cookie(SSO_FLOW_COOKIE, path=SSO_CALLBACK_PATH)
        response.set_cookie(
            key=SSO_HANDOFF_COOKIE,
            value=token,
            max_age=SSO_HANDOFF_TTL_SECONDS,
            httponly=True,
            secure=_cookie_secure(request),
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
        from .serializers import UserSerializer
        response = Response({'token': token, 'user': UserSerializer(user).data})
        response.delete_cookie(SSO_HANDOFF_COOKIE, path='/api/auth/sso/exchange')
        return response
