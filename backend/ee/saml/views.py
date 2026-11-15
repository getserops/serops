"""SAML endpoints (Enterprise, feature ``saml``).

    GET  /api/ee/saml/<sp_id>/metadata/   our SP metadata (public)
    POST /api/ee/saml/<sp_id>/acs/        the identity provider posts the response here (public)
    GET  /api/ee/saml/config/             settings page
    PUT  /api/ee/saml/config/             settings page (license required)

Without the license every public endpoint answers as if SAML did not
exist (404, or the login page with ?sso=failed) and the settings page
shows the Enterprise note; the configuration is kept.
"""
import logging

from django.http import HttpResponse
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.rbac import ROLE_PERMISSIONS, Requires, can_grant
from Utils import edition

from . import service

logger = logging.getLogger(__name__)

FEATURE = 'saml'


def _config_by_sp_id(sp_id):
    from ee.models import SamlConfig
    return SamlConfig.objects.select_related('organisation').filter(sp_id=sp_id).first()


class SamlMetadataView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, sp_id):
        config = _config_by_sp_id(sp_id)
        if config is None or not edition.has_feature(FEATURE):
            return HttpResponse(status=404)
        try:
            xml = service.metadata_xml(config)
        except service.SamlError:
            logger.exception('SAML metadata failed for org %s', config.organisation_id)
            return HttpResponse(status=500)
        response = HttpResponse(xml, content_type='application/samlmetadata+xml')
        response['Content-Disposition'] = 'inline; filename="serops-saml-metadata.xml"'
        return response


class SamlAcsView(APIView):
    """Assertion Consumer Service (HTTP-POST binding).

    Every failure sends the browser to the login page with ?sso=failed; the
    reason is in the server log, never in the page. RelayState is ignored:
    the browser always lands on the app, so it cannot be used to redirect
    anywhere else.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # also: no CSRF check, the identity provider posts cross-site
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_saml_acs'

    def post(self, request, sp_id):
        from Users.sso_views import _sso_settings_for, _validated_frontend_url, complete_sign_in
        from Users.views import demo_only_login
        failed = redirect(f'{_validated_frontend_url()}/login?sso=failed')
        saml_response = request.POST.get('SAMLResponse') or ''
        if demo_only_login() or not saml_response or len(saml_response) > 2 * service.METADATA_MAX_BYTES:
            return failed
        config = _config_by_sp_id(sp_id)
        if config is None:
            return failed
        # Inert without the license, and only while SAML is this
        # organisation's SSO and switched on.
        sec_settings = _sso_settings_for(config.organisation_id, 'saml')
        if sec_settings is None or not service.is_configured(config):
            logger.warning('SAML response for org %s, whose SAML sign-in is off or unlicensed', config.organisation_id)
            return failed
        try:
            identity = service.process_response(config, sec_settings, saml_response)
        except service.SamlError as exc:
            logger.warning('SAML response refused for org %s: %s', config.organisation_id, exc)
            log_action(request, 'SSO_DENIED', {'source': 'saml', 'reason': str(exc)[:300]},
                       organisation=config.organisation)
            return failed
        except Exception:
            logger.exception('SAML response failed for org %s', config.organisation_id)
            return failed
        return complete_sign_in(
            request, sec_settings, email=identity.email, groups=identity.groups,
            first_name=identity.first_name, last_name=identity.last_name, source='saml')


def _config_payload(config, sec_settings):
    certs = []
    for body in config.idp_certificates or []:
        try:
            certs.append(service.certificate_summary(body))
        except Exception:
            certs.append({'subject': 'unreadable certificate'})
    return {
        'licensed': edition.has_feature(FEATURE),
        'configured': service.is_configured(config),
        'active': bool(sec_settings and sec_settings.sso_enabled and sec_settings.sso_provider == 'saml'),
        # What the admin registers at the identity provider.
        'sp_entity_id': service.sp_entity_id(config),
        'acs_url': service.acs_url(config),
        'metadata_url': service.sp_entity_id(config),
        'sp_certificate': config.sp_certificate,
        # What we know of the identity provider.
        'idp_metadata_url': config.idp_metadata_url,
        'idp_entity_id': config.idp_entity_id,
        'idp_sso_url': config.idp_sso_url,
        'idp_certificates': certs,
        'idp_metadata_fetched_at': config.idp_metadata_fetched_at.isoformat() if config.idp_metadata_fetched_at else None,
        'email_attribute': config.email_attribute,
        'first_name_attribute': config.first_name_attribute,
        'last_name_attribute': config.last_name_attribute,
        'want_assertions_encrypted': config.want_assertions_encrypted,
        'allow_idp_initiated': config.allow_idp_initiated,
        'clock_skew_seconds': service.CLOCK_SKEW_SECONDS,
        'single_logout': False,
    }


class SamlConfigView(APIView):
    """The organisation's SAML settings (Settings → Security → Single sign-on)."""

    permission_classes = [IsAuthenticated, Requires(GET='settings.read', PUT='settings.manage')]

    IDENTITY_FIELDS = ('idp_metadata_url', 'idp_metadata_xml', 'idp_entity_id', 'idp_sso_url', 'idp_certificate',
                       'email_attribute', 'refresh_metadata', 'allow_idp_initiated', 'want_assertions_encrypted')

    def get(self, request):
        from Users.models import SecuritySettings
        org = request.user.organisation
        if org is None:
            return Response({'error': 'User does not belong to an organization'}, status=400)
        config = service.get_or_create_config(org)
        return Response(_config_payload(config, SecuritySettings.objects.filter(organisation=org).first()))

    def put(self, request):
        from django.utils import timezone

        from Users.models import SecuritySettings
        org = request.user.organisation
        if org is None:
            return Response({'error': 'User does not belong to an organization'}, status=400)
        if not edition.has_feature(FEATURE):
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        data = request.data
        # The identity provider decides who signs in as whom, as with OIDC.
        if any(k in data for k in self.IDENTITY_FIELDS) and not can_grant(request.user, ROLE_PERMISSIONS['admin']):
            return Response({'error': 'Changing the identity provider needs every permission of an admin.'},
                            status=403)
        config = service.get_or_create_config(org)
        changed = []
        try:
            metadata = None
            if 'idp_metadata_url' in data:
                url = str(data.get('idp_metadata_url') or '').strip()
                if url != config.idp_metadata_url:
                    config.idp_metadata_url = url[:1024]
                    changed.append('idp_metadata_url')
            if data.get('idp_metadata_xml'):
                metadata = data['idp_metadata_xml']
                changed.append('idp_metadata')
            elif config.idp_metadata_url and ('idp_metadata_url' in changed or data.get('refresh_metadata')):
                # Fetched by the server: the same outbound checks as every
                # URL an admin sets (no cloud metadata, optional private block).
                from Utils.url_validator import validate_outbound_url
                try:
                    validate_outbound_url(config.idp_metadata_url)
                except ValueError as exc:
                    return Response({'error': f'idp_metadata_url: {exc}'}, status=400)
                try:
                    metadata = service.fetch_idp_metadata(config.idp_metadata_url)
                except service.SamlError:
                    raise
                except Exception as exc:
                    logger.warning('SAML metadata download failed for org %s: %s', org.pk, exc)
                    return Response({'error': 'Could not download the metadata from that URL.'}, status=400)
                changed.append('idp_metadata')
            if metadata is not None:
                config.idp_entity_id, config.idp_sso_url, config.idp_certificates = service.parse_idp_metadata(metadata)
                config.idp_metadata_fetched_at = timezone.now()
            else:
                # Without metadata: the three values typed in.
                if 'idp_entity_id' in data:
                    config.idp_entity_id = str(data['idp_entity_id'] or '').strip()[:1024]
                    changed.append('idp_entity_id')
                if 'idp_sso_url' in data:
                    sso_url = str(data['idp_sso_url'] or '').strip()
                    if sso_url and not sso_url.startswith(('https://', 'http://')):
                        return Response({'error': 'idp_sso_url must be an http(s) URL'}, status=400)
                    config.idp_sso_url = sso_url[:1024]
                    changed.append('idp_sso_url')
                if data.get('idp_certificate'):
                    config.idp_certificates = [service.normalise_certificate(data['idp_certificate'])]
                    changed.append('idp_certificate')
        except service.SamlError as exc:
            return Response({'error': str(exc)}, status=400)

        for field in ('email_attribute', 'first_name_attribute', 'last_name_attribute'):
            if field in data:
                value = str(data[field] or '').strip()
                if len(value) > 512:
                    return Response({'error': f'{field} is too long'}, status=400)
                setattr(config, field, value)
                changed.append(field)
        for field in ('want_assertions_encrypted', 'allow_idp_initiated'):
            if field in data:
                setattr(config, field, bool(data[field]))
                changed.append(field)
        config.save()
        if changed:
            log_action(request, 'SETTINGS_CHANGE', {'setting': 'saml', 'changed': sorted(set(changed)),
                                                    'idp_entity_id': config.idp_entity_id})
        return Response(_config_payload(config, SecuritySettings.objects.filter(organisation=org).first()))
