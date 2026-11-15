"""Audit streams of an organisation (Settings → Audit Log → Streaming).

    GET    /api/ee/audit-streams/              destinations, their state, and whether the license allows streaming
    POST   /api/ee/audit-streams/              add one
    GET    /api/ee/audit-streams/<id>/         one destination
    PUT    /api/ee/audit-streams/<id>/         change it (secrets: send a value to set, "" to clear, omit to keep)
    DELETE /api/ee/audit-streams/<id>/         remove it
    POST   /api/ee/audit-streams/<id>/test/    send a test event now and say what happened

Reading takes the audit log's own permission (team.manage). Adding,
changing or removing a destination takes every permission of an admin:
a destination receives the organisation's whole audit trail. Secrets are
write-only. Turning a destination off, or removing it, is itself recorded
and delivered to it first, so the SIEM sees the stream being stopped.
"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.rbac import ROLE_PERMISSIONS, Requires, can_grant
from Utils import crypto, edition
from Utils.url_validator import validate_outbound_url

from . import service, transports

FEATURE = service.FEATURE
_HEADER_NAME = re.compile(r'^[A-Za-z0-9!#$%&\'*+.^_`|~-]{1,100}$')
_HOST = re.compile(r'^[A-Za-z0-9.:\[\]-]{1,255}$')
DEFAULT_PORTS = {'tls': 6514, 'tcp': 514, 'udp': 514}


def _row(d):
    target = d.url if d.kind == d.KIND_HTTP else f'{d.host}:{d.port}'
    return {
        'id': d.pk, 'name': d.name, 'kind': d.kind, 'enabled': d.enabled, 'target': target,
        'url': d.url, 'http_format': d.http_format, 'auth_header_name': d.auth_header_name,
        'auth_header_configured': bool(d.auth_header_value_encrypted),
        'signing_secret_configured': bool(d.signing_secret_encrypted),
        'host': d.host, 'port': d.port, 'transport': d.transport, 'ca_certificate': d.ca_certificate,
        'created_at': d.created_at.isoformat(), 'created_by': d.created_by.email if d.created_by else None,
        'last_success_at': d.last_success_at.isoformat() if d.last_success_at else None,
        'last_failure_at': d.last_failure_at.isoformat() if d.last_failure_at else None,
        'last_error': d.last_error, 'delivered_count': d.delivered_count,
        **service.status(d),
    }


def _admin_only(request):
    if not can_grant(request.user, ROLE_PERMISSIONS['admin']):
        return Response({'error': 'Audit streams take every permission of an admin.'}, status=403)
    return None


def _private(host):
    try:
        candidates = [ipaddress.ip_address(host.strip('[]'))]
    except ValueError:
        try:
            candidates = [ipaddress.ip_address(ai[4][0]) for ai in socket.getaddrinfo(host, None)]
        except (socket.gaierror, ValueError):
            return False
    return bool(candidates) and all(ip.is_private or ip.is_loopback for ip in candidates)


def _check_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.hostname:
        raise ValueError('The URL must start with https://')
    if parts.scheme == 'http' and not (getattr(settings, 'OUTBOUND_ALLOW_PRIVATE_URLS', True)
                                       and _private(parts.hostname)):
        raise ValueError('Use https:// (plain http is accepted only for a collector on a private network).')
    if parts.username or parts.password:
        raise ValueError('Put credentials in the authorization header, not in the URL.')
    validate_outbound_url(url)
    return url


def _apply(destination, data, *, creating):
    """Validate ``data`` onto ``destination``. Returns the names changed. Raises ValueError."""
    changed = []

    def put(field, value):
        if getattr(destination, field) != value:
            setattr(destination, field, value)
            changed.append(field)

    if 'name' in data or creating:
        name = str(data.get('name') or '').strip()
        if not name or len(name) > 100:
            raise ValueError('Give the destination a name (at most 100 characters).')
        put('name', name)
    if creating:
        kind = data.get('kind')
        if kind not in (destination.KIND_HTTP, destination.KIND_SYSLOG):
            raise ValueError('kind must be "http" or "syslog".')
        destination.kind = kind
    if 'enabled' in data:
        put('enabled', bool(data['enabled']))
    if 'ca_certificate' in data:
        pem = str(data['ca_certificate'] or '').strip()
        if pem:
            try:
                transports.tls_context(pem)
            except Exception:
                raise ValueError('The CA certificate is not a valid PEM certificate.') from None
        put('ca_certificate', pem)

    if destination.kind == destination.KIND_HTTP:
        if 'url' in data or creating:
            put('url', _check_url(str(data.get('url') or '').strip()[:1024]))
        if 'http_format' in data:
            if data['http_format'] not in dict(destination.FORMATS):
                raise ValueError('http_format must be json, ndjson or splunk_hec.')
            put('http_format', data['http_format'])
        if 'auth_header_name' in data:
            name = str(data['auth_header_name'] or '').strip()
            if name and not _HEADER_NAME.match(name):
                raise ValueError('The header name may contain letters, digits and - only.')
            put('auth_header_name', name)
        if 'auth_header_value' in data:
            value = str(data['auth_header_value'] or '')
            if '\r' in value or '\n' in value:
                raise ValueError('The header value cannot contain line breaks.')
            destination.auth_header_value_encrypted = crypto.encrypt(value) if value else ''
            changed.append('auth_header_value')
        if 'signing_secret' in data:
            value = str(data['signing_secret'] or '')
            destination.signing_secret_encrypted = crypto.encrypt(value) if value else ''
            changed.append('signing_secret')
        if destination.auth_header_value_encrypted and not destination.auth_header_name:
            raise ValueError('Name the header the value goes in (for example Authorization).')
    else:
        if 'transport' in data:
            if data['transport'] not in DEFAULT_PORTS:
                raise ValueError('transport must be tls, tcp or udp.')
            put('transport', data['transport'])
        if 'host' in data or creating:
            host = str(data.get('host') or '').strip()
            if not _HOST.match(host):
                raise ValueError('Give the syslog host name or address.')
            put('host', host)
        if 'port' in data or creating:
            try:
                port = int(data.get('port') or DEFAULT_PORTS[destination.transport])
            except (TypeError, ValueError):
                raise ValueError('The port must be a number.') from None
            if not 1 <= port <= 65535:
                raise ValueError('The port must be between 1 and 65535.')
            put('port', port)
        try:
            transports.resolve(destination.host, destination.port, destination.transport)
        except transports.DeliveryError as exc:
            if 'outbound policy' in str(exc):
                raise ValueError(str(exc)) from None  # unresolvable now is fine: it may come up later
    return changed


def _org(request):
    return request.user.organisation


class AuditStreamsView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='team.manage', POST='settings.manage')]

    def get(self, request):
        from ee.models import AuditStreamDestination
        rows = AuditStreamDestination.objects.filter(organisation=_org(request)).select_related('created_by')
        return Response({'licensed': edition.has_feature(FEATURE), 'destinations': [_row(d) for d in rows.order_by('name')]})

    def post(self, request):
        from ee.models import AuditStreamDestination
        if not edition.has_feature(FEATURE):
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        refused = _admin_only(request)
        if refused:
            return refused
        destination = AuditStreamDestination(organisation=_org(request), created_by=request.user)
        try:
            _apply(destination, request.data, creating=True)
            destination.save()
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except IntegrityError:
            return Response({'error': 'A destination with this name exists.'}, status=400)
        log_action(request, 'AUDIT_STREAM_CREATE', {'name': destination.name, 'kind': destination.kind,
                                                     'target': _row(destination)['target']})
        return Response(_row(destination), status=201)


class AuditStreamDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='team.manage', PUT='settings.manage',
                                                    DELETE='settings.manage')]

    def _get(self, request, pk):
        from ee.models import AuditStreamDestination
        return AuditStreamDestination.objects.filter(organisation=_org(request), pk=pk).first()

    def get(self, request, pk):
        destination = self._get(request, pk)
        if destination is None:
            return Response({'error': 'Not found'}, status=404)
        return Response(_row(destination))

    def put(self, request, pk):
        destination = self._get(request, pk)
        if destination is None:
            return Response({'error': 'Not found'}, status=404)
        refused = _admin_only(request)
        if refused:
            return refused
        turning_off = destination.enabled and request.data.get('enabled') is False
        # Without the license the only change allowed is turning it off.
        only_turning_off = set(request.data) == {'enabled'} and request.data.get('enabled') is False
        if not edition.has_feature(FEATURE) and not only_turning_off:
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        if turning_off:
            # Recorded while still on, and sent, so the SIEM sees the stream stop.
            log_action(request, 'AUDIT_STREAM_UPDATE', {'name': destination.name, 'changed': ['enabled'],
                                                         'enabled': False})
            service.deliver(destination.pk)
            destination.refresh_from_db()
        try:
            changed = _apply(destination, request.data, creating=False)
            destination.save()
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)
        except IntegrityError:
            return Response({'error': 'A destination with this name exists.'}, status=400)
        changed = [c for c in changed if not (turning_off and c == 'enabled')]
        if changed:
            log_action(request, 'AUDIT_STREAM_UPDATE', {'name': destination.name, 'changed': changed,
                                                         'enabled': destination.enabled})
        return Response(_row(destination))

    def delete(self, request, pk):
        destination = self._get(request, pk)
        if destination is None:
            return Response({'error': 'Not found'}, status=404)
        refused = _admin_only(request)
        if refused:
            return refused
        log_action(request, 'AUDIT_STREAM_DELETE', {'name': destination.name, 'kind': destination.kind,
                                                     'target': _row(destination)['target']})
        service.deliver(destination.pk)
        destination.delete()
        return Response(status=204)


class AuditStreamTestView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='settings.manage')]

    def post(self, request, pk):
        from ee.models import AuditStreamDestination
        from . import events as wire
        destination = AuditStreamDestination.objects.filter(organisation=_org(request), pk=pk).first()
        if destination is None:
            return Response({'error': 'Not found'}, status=404)
        if not edition.has_feature(FEATURE):
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        refused = _admin_only(request)
        if refused:
            return refused
        try:
            service.send(destination, [wire.test_event(destination.organisation, request.user)])
        except transports.DeliveryError as exc:
            return Response({'ok': False, 'error': str(exc)})
        return Response({'ok': True})
