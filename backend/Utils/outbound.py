"""Outbound HTTP to user-configured URLs, checked on every hop.

Security review 2026-11, finding 3: user-supplied URLs were checked once,
when saved, and the request then followed redirects. A server that passed
the check could answer ``302 Location: http://169.254.169.254/...`` and the
backend fetched the metadata endpoint with the integration's credentials.

Policy, for both helpers below:

* the URL is validated before every request, with
  ``validate_outbound_url`` by default (see ``Utils.url_validator`` for the
  private-address policy);
* redirects are followed only within the same origin (scheme, host, port),
  re-validated on each hop. A redirect to another origin is returned as is,
  not followed: following it could reach an address the check never saw,
  and would send the integration's credentials (custom headers such as
  ``PRIVATE-TOKEN`` or ``DD-API-KEY``, which requests does not strip) to
  another host.
"""

from urllib.parse import urljoin, urlparse

import requests

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


class GuardedSession(requests.Session):
    """``requests.Session`` that validates every request it sends.

    ``send`` runs for the first request and for each redirect hop, so both
    are checked; ``get_redirect_target`` stops at a cross-origin redirect.
    """

    def __init__(self, validator=validate_outbound_url):
        super().__init__()
        self._validator = validator
        self.max_redirects = MAX_REDIRECTS

    def send(self, request, **kwargs):
        check_url(request.url, self._validator)
        return super().send(request, **kwargs)

    def get_redirect_target(self, resp):
        target = super().get_redirect_target(resp)
        if target and _origin(urljoin(resp.url, target)) != _origin(resp.url):
            return None
        return target


def guarded_request(method, url, *, validator=validate_outbound_url, **kwargs):
    """``requests.request`` with the same policy as ``GuardedSession``.

    Goes through the module-level ``requests.request`` (with
    ``allow_redirects=False`` and redirects handled here), so code and tests
    that patch ``requests.request`` keep working.
    """
    kwargs['allow_redirects'] = False
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url, validator)
        response = requests.request(method=method, url=url, **kwargs)
        code = getattr(response, 'status_code', None)
        if not isinstance(code, int) or code not in _REDIRECT_CODES:
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
