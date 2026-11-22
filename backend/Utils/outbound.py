"""Outbound HTTP to user-configured URLs, checked on every hop.

Security review 2026-11, finding 3: user-supplied URLs were checked once,
when saved, and the request then followed redirects. A server that passed
the check could answer ``302 Location: http://169.254.169.254/...`` and the
backend fetched the metadata endpoint with the integration's credentials.

Policy, for both helpers below:

* the URL is validated before every request, with
  ``validate_outbound_url`` by default (see ``Utils.url_validator`` for the
  private-address policy);
* the host name is resolved once, every address it resolves to is checked
  with the same validator, and the connection goes to a checked address
  (``PinnedAdapter``): the check and the connection can no longer see two
  different DNS answers (audit 2026-11-20, item 3). The Host header, TLS
  SNI and certificate hostname check still use the name;
* redirects are followed only within the same origin (scheme, host, port),
  re-validated on each hop. A redirect to another origin is returned as is,
  not followed: following it could reach an address the check never saw,
  and would send the integration's credentials (custom headers such as
  ``PRIVATE-TOKEN`` or ``DD-API-KEY``, which requests does not strip) to
  another host.
"""

import ipaddress
import socket
import threading
from urllib.parse import urljoin, urlparse

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

from Utils import query_trail
from Utils.url_validator import validate_outbound_url

_REDIRECT_CODES = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5


class BlockedOutboundURL(requests.exceptions.InvalidURL):
    """The destination is refused by the outbound URL policy.

    A ``requests.RequestException`` (and ``ValueError``), so callers that
    already handle request failures handle this one too.
    """


def _origin(url):
    parsed = urlparse(url)
    port = parsed.port or {'http': 80, 'https': 443}.get(parsed.scheme)
    return parsed.scheme, (parsed.hostname or '').lower(), port


def check_url(url, validator=validate_outbound_url):
    try:
        validator(url)
    except ValueError as exc:
        raise BlockedOutboundURL(str(exc)) from exc
    return url


def _literal(host):
    try:
        return ipaddress.ip_address(host.strip('[]'))
    except ValueError:
        return None


def resolve_checked(url, validator=validate_outbound_url):
    """The addresses to connect to for ``url``, each one allowed by ``validator``.

    Resolves the host once. Every address it resolves to must pass (one
    refused address refuses the URL, as ``validator`` does on its own), and
    each is checked by giving the validator a URL with that literal address,
    so the address policy stays in one place (``Utils.url_validator``).
    """
    check_url(url, validator)
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if _literal(host) is not None:
        return [str(_literal(host))]
    port = parsed.port or {'http': 80, 'https': 443}.get(parsed.scheme, 443)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise requests.exceptions.ConnectionError(f'Could not resolve {host}: {exc}') from exc
    addresses = list(dict.fromkeys(info[4][0].split('%', 1)[0] for info in infos))
    if not addresses:
        raise requests.exceptions.ConnectionError(f'{host} did not resolve')
    for address in addresses:
        literal = f'[{address}]' if ':' in address else address
        check_url(f'{parsed.scheme}://{literal}:{port}/', validator)
    return addresses


def _never_connected(exc):
    """Whether a requests ConnectionError happened before a connection existed."""
    from urllib3.exceptions import ConnectTimeoutError, MaxRetryError, NewConnectionError
    if isinstance(exc, requests.exceptions.SSLError):
        return False
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return True
    reason = exc.args[0] if exc.args else None
    if isinstance(reason, MaxRetryError):
        reason = reason.reason
    return isinstance(reason, (NewConnectionError, ConnectTimeoutError))


class PinnedAdapter(HTTPAdapter):
    """Transport adapter that connects only to an address checked for this
    request (see ``resolve_checked``). Tries the checked addresses in order
    until one connects. With a proxy configured the proxy resolves the name,
    so the request goes through the stock adapter after the URL check.
    """

    def __init__(self, validator=validate_outbound_url, **kwargs):
        self._validator = validator
        self._pinned = threading.local()
        self._pools = {}
        self._pools_lock = threading.Lock()
        super().__init__(**kwargs)

    def send(self, request, **kwargs):
        proxies = kwargs.get('proxies') or {}
        if requests.utils.select_proxy(request.url, proxies):
            check_url(request.url, self._validator)
            return super().send(request, **kwargs)
        addresses = resolve_checked(request.url, self._validator)
        parsed = urlparse(request.url)
        if _literal(parsed.hostname or '') is None and 'Host' not in request.headers:
            # The pool connects to the address; the Host header keeps the name.
            request.headers['Host'] = parsed.netloc.rsplit('@', 1)[-1]
        last_error = None
        for address in addresses:
            self._pinned.ip = address
            try:
                return super().send(request, **kwargs)
            except requests.exceptions.ConnectionError as exc:
                # Next address only when this one never connected. A TLS
                # refusal or a connection dropped after sending is the
                # answer, not a reason to send the request again elsewhere.
                if not _never_connected(exc):
                    raise
                last_error = exc
            finally:
                self._pinned.ip = None
        raise last_error

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        address = getattr(self._pinned, 'ip', None)
        if not address or (proxies and requests.utils.select_proxy(request.url, proxies)):
            return super().get_connection_with_tls_context(request, verify, proxies=proxies, cert=cert)
        parsed = urlparse(request.url)
        https = parsed.scheme == 'https'
        port = parsed.port or (443 if https else 80)
        name = (parsed.hostname or '').lower()
        key = (parsed.scheme, name, port, address)
        with self._pools_lock:
            pool = self._pools.get(key)
            if pool is None:
                if https:
                    # Connect to the address; SNI and the certificate check
                    # use the name.
                    pool = HTTPSConnectionPool(address, port, maxsize=self._pool_maxsize, block=self._pool_block,
                                               server_hostname=name, assert_hostname=name)
                else:
                    pool = HTTPConnectionPool(address, port, maxsize=self._pool_maxsize, block=self._pool_block)
                self._pools[key] = pool
        return pool

    def close(self):
        with self._pools_lock:
            for pool in self._pools.values():
                pool.close()
            self._pools.clear()
        super().close()


class GuardedSession(requests.Session):
    """``requests.Session`` that validates every request it sends.

    ``send`` runs for the first request and for each redirect hop, so both
    are checked; ``get_redirect_target`` stops at a cross-origin redirect.
    """

    def __init__(self, validator=validate_outbound_url):
        super().__init__()
        self._validator = validator
        self.max_redirects = MAX_REDIRECTS
        adapter = PinnedAdapter(validator)
        self.mount('http://', adapter)
        self.mount('https://', adapter)

    def send(self, request, **kwargs):
        check_url(request.url, self._validator)
        if not query_trail.active():
            return super().send(request, **kwargs)
        started = time.monotonic()
        try:
            response = super().send(request, **kwargs)
        except Exception as exc:
            _trail(request.method, request.url, request.body, None, exc, started)
            raise
        _trail(request.method, request.url, request.body, response, None, started)
        return response

    def get_redirect_target(self, resp):
        target = super().get_redirect_target(resp)
        if target and _origin(urljoin(resp.url, target)) != _origin(resp.url):
            return None
        return target


def _trail(method, url, body, response, error, started):
    """Record the exchange in the query trail when one is active
    (``Utils.query_trail``; off unless SEROPS_QUERY_TRAIL_DIR is set)."""
    if not query_trail.active():
        return
    status, answer = None, None
    if response is not None:
        # The URL as sent, query parameters included (guarded_request gets
        # them as ``params=``).
        url = getattr(getattr(response, 'request', None), 'url', None) or url
        status = getattr(response, 'status_code', None)
        try:
            answer = response.content
        except Exception as exc:                        # noqa: BLE001
            error = error or exc
    query_trail.record(query_trail.host_of(url), method, url, request_body=body,
                       status=status, response_body=answer, error=error, started=started)


def guarded_request(method, url, *, validator=validate_outbound_url, follow_redirects=True, **kwargs):
    """``requests.request`` with the same policy as ``GuardedSession``:
    each hop is sent by ``_send`` through a ``PinnedAdapter``, with
    ``allow_redirects=False`` and redirects handled here. Tests patch
    ``Utils.outbound._send``.
    """
    kwargs['allow_redirects'] = False
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, validator)
        started = time.monotonic()
        try:
            _hop.validator = validator
            try:
                response = _send(method=method, url=url, **kwargs)
            finally:
                _hop.validator = None
        except Exception as exc:
            _trail(method, url, kwargs.get('json', kwargs.get('data')), None, exc, started)
            raise
        _trail(method, url, kwargs.get('json', kwargs.get('data')), response, None, started)
        code = getattr(response, 'status_code', None)
        if not follow_redirects or not isinstance(code, int) or code not in _REDIRECT_CODES:
            return response
        location = (getattr(response, 'headers', None) or {}).get('Location')
        if not location:
            return response
        target = urljoin(url, location)
        if _origin(target) != _origin(url):
            return response
        if code in (301, 302, 303) and method.upper() != 'HEAD':
            method = 'GET'
            kwargs.pop('data', None)
            kwargs.pop('json', None)
        url = target
    raise requests.exceptions.TooManyRedirects(f'More than {MAX_REDIRECTS} redirects from {url}')


# The validator of the hop ``guarded_request`` is sending; ``_send`` keeps
# ``requests.request``'s signature, so tests patch it and assert on the same
# arguments as before.
_hop = threading.local()


def _send(method, url, **kwargs):
    """One request, connected to an address checked for it (``PinnedAdapter``)."""
    validator = getattr(_hop, 'validator', None) or validate_outbound_url
    with requests.Session() as session:
        adapter = PinnedAdapter(validator)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session.request(method=method, url=url, **kwargs)


# Drop-in replacements for ``requests.get`` and friends, same signatures, for
# code that calls a user-configured URL (audit 2026-11-20, item 3). A caller
# that passed ``allow_redirects=False`` gets no redirect followed, as before;
# otherwise same-origin redirects are followed and checked (guarded_request).
def request(method, url, **kwargs):
    follow = kwargs.pop('allow_redirects', True) is not False
    return guarded_request(method, url, follow_redirects=follow, **kwargs)


def get(url, params=None, **kwargs):
    return request('GET', url, params=params, **kwargs)


def post(url, data=None, json=None, **kwargs):
    return request('POST', url, data=data, json=json, **kwargs)


def put(url, data=None, **kwargs):
    return request('PUT', url, data=data, **kwargs)


def patch(url, data=None, **kwargs):
    return request('PATCH', url, data=data, **kwargs)


def delete(url, **kwargs):
    return request('DELETE', url, **kwargs)
