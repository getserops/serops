"""Sending a batch of events to a destination: HTTPS or syslog.

Both go through the install's outbound policy (``Utils.url_validator``):
cloud metadata and link-local addresses are always refused, private ones
unless ``SEROPS_OUTBOUND_ALLOW_PRIVATE`` allows them. HTTP uses
``GuardedSession`` (checked on every redirect hop). Syslog resolves the
host once, checks each address, and connects to that address, so a DNS
answer cannot change between the check and the connection.

Errors are ``DeliveryError`` with a message safe to show and store: never
a secret, never the response body.
"""
import hashlib
import hmac
import ipaddress
import os
import socket
import ssl
import tempfile
import time

from Utils.outbound import BlockedOutboundURL, GuardedSession
from Utils.url_validator import validate_outbound_url

from . import events as wire

TIMEOUT = 10  # seconds, per connection or request


class DeliveryError(Exception):
    pass


def signature(secret, timestamp, body):
    """``X-SerOps-Signature``: HMAC-SHA256 of "<timestamp>.<body>", hex, prefixed "sha256="."""
    mac = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + body, hashlib.sha256)
    return 'sha256=' + mac.hexdigest()


def send_http(url, events, *, fmt='json', auth_header=None, signing_secret=None, ca_pem=''):
    body, content_type = wire.http_body(events, fmt)
    headers = {'Content-Type': content_type, 'User-Agent': 'SerOps-AuditStream/1'}
    if auth_header:
        name, value = auth_header
        headers[name] = value
    if signing_secret:
        ts = int(time.time())
        headers['X-SerOps-Timestamp'] = str(ts)
        headers['X-SerOps-Signature'] = signature(signing_secret, ts, body)
    ca_file = None
    try:
        verify = True
        if ca_pem:
            # requests verifies against a file: the destination's CA only.
            fd, ca_file = tempfile.mkstemp(suffix='.pem')
            with os.fdopen(fd, 'w') as f:
                f.write(ca_pem)
            verify = ca_file
        with GuardedSession() as session:
            response = session.post(url, data=body, headers=headers, timeout=TIMEOUT, allow_redirects=False,
                                    verify=verify)
    except BlockedOutboundURL as exc:
        raise DeliveryError(f'Destination refused by the outbound policy: {exc}') from exc
    except Exception as exc:  # requests' connection, TLS and timeout errors
        if 'CERTIFICATE_VERIFY_FAILED' in str(exc):
            raise DeliveryError('TLS certificate of the destination not trusted') from exc
        raise DeliveryError(f'Could not reach the destination ({exc.__class__.__name__})') from exc
    finally:
        if ca_file:
            os.unlink(ca_file)
    if not 200 <= response.status_code < 300:
        raise DeliveryError(f'The destination answered HTTP {response.status_code}')
    return len(events)


def _check_address(ip, port):
    host = f'[{ip}]' if ip.version == 6 else str(ip)
    try:
        validate_outbound_url(f'https://{host}:{port}/')
    except ValueError as exc:
        raise DeliveryError(f'Destination refused by the outbound policy: {exc}') from exc


def resolve(host, port, transport):
    """Every address of ``host`` the outbound policy allows, in resolver order (sockaddr tuples).

    All of them, not the first: "localhost" or a dual-stack host often lists
    ::1 / an IPv6 address first, and a collector listening on IPv4 only must
    still be reached (as socket.create_connection does).
    """
    kind = socket.SOCK_DGRAM if transport == 'udp' else socket.SOCK_STREAM
    try:
        infos = socket.getaddrinfo(host, port, type=kind)
    except socket.gaierror as exc:
        raise DeliveryError(f'Cannot resolve {host}') from exc
    allowed, error = [], None
    for family, socktype, proto, _, sockaddr in infos:
        try:
            _check_address(ipaddress.ip_address(sockaddr[0]), port)
        except DeliveryError as exc:
            error = exc
            continue
        allowed.append((family, socktype, proto, sockaddr))
    if not allowed:
        raise error or DeliveryError(f'Cannot resolve {host}')
    return allowed


def _connect(addresses):
    """A TCP socket connected to the first address that answers."""
    error = None
    for family, socktype, proto, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(TIMEOUT)
        try:
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            sock.close()
            error = exc
    raise error


def tls_context(ca_pem=''):
    context = ssl.create_default_context(cadata=ca_pem or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def send_syslog(host, port, transport, events, *, ca_pem=''):
    messages = [wire.syslog_message(e) for e in events]
    addresses = resolve(host, port, transport)
    try:
        if transport == 'udp':
            # No connection to try: the first allowed address (UDP gives no answer either way).
            family, socktype, proto, sockaddr = addresses[0]
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(TIMEOUT)
                for message in messages:
                    sock.sendto(message, sockaddr)
            return len(events)
        raw = _connect(addresses)
        try:
            sock = tls_context(ca_pem).wrap_socket(raw, server_hostname=host) if transport == 'tls' else raw
            with sock:
                sock.sendall(b''.join(wire.octet_counted(m) for m in messages))
                if transport == 'tls':
                    # close_notify, so the collector knows the stream ended cleanly
                    # rather than being cut (some drop the last frames otherwise).
                    try:
                        sock.unwrap()
                    except (ssl.SSLError, OSError):
                        pass
        finally:
            raw.close()
    except ssl.SSLCertVerificationError as exc:
        raise DeliveryError(f'TLS certificate not trusted for {host} ({exc.verify_message})') from exc
    except ssl.SSLError as exc:
        raise DeliveryError(f'TLS handshake with {host} failed ({exc.reason or exc.__class__.__name__})') from exc
    except OSError as exc:
        raise DeliveryError(f'Could not send to {host}:{port} ({exc.__class__.__name__})') from exc
    return len(events)
