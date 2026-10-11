"""URL validation helpers for outbound HTTP calls.

The onboarding wizard, webhook test view, and any future user-supplied
URL destination should route through :func:`validate_public_url` before
handing the value to ``requests.*``. Reason: an authenticated org admin
should not be able to point a webhook at ``169.254.169.254`` (AWS
metadata), ``localhost:8000/admin`` (bypass auth by hitting our own
service from inside the network), or a coworker's internal Grafana.

Scope of protection:
- Enforces ``https://`` (blocks ``file://``, ``gopher://``, unsigned
  ``http://`` traffic).
- Rejects any resolvable hostname that maps to a private / loopback /
  link-local / reserved range at *validation time*. This is a
  best-effort check — DNS answers can change between validation and
  the actual request (DNS-rebinding attack), but most CI+prod
  environments will still catch the obvious cases.

Callers wanting hardening past DNS-rebinding should use an
IP-pinned session or a dedicated egress proxy — out of scope here.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Rest of the codebase raises DRF ValidationError from serializers.
# Utils shouldn't take a DRF dependency, so we raise a plain ValueError
# and let the caller convert.


def validate_public_url(url: str) -> str:
    """Return the URL if safe to fetch, else raise ``ValueError``.

    Safe means:
      - scheme is ``https``
      - hostname is present
      - every A/AAAA record for the hostname is a public routable
        address (not RFC1918, loopback, link-local, or reserved)

    Empty / falsy input raises immediately — callers who allow
    optional URLs should guard before calling.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL is required.")

    parsed = urlparse(url)

    if parsed.scheme != 'https':
        raise ValueError("URL must use https://")

    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname.")

    # Reject any hostname that literally IS a private / loopback IP.
    # ipaddress.ip_address raises ValueError on non-IP hostnames — that
    # falls through to DNS resolution below.
    try:
        ip = ipaddress.ip_address(host)
        if _is_disallowed_ip(ip):
            raise ValueError(
                f"URL points at a non-public address ({host})."
            )
        return url
    except ValueError as exc:
        # If _is_disallowed_ip raised above, propagate as-is.
        if 'non-public' in str(exc):
            raise
        # Otherwise host is a name, not an IP — resolve it.

    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname {host!r}: {exc}") from exc

    resolved_ips = {ai[4][0] for ai in addrinfo}
    if not resolved_ips:
        raise ValueError(f"Hostname {host!r} did not resolve.")

    for raw in resolved_ips:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _is_disallowed_ip(ip):
            raise ValueError(
                f"Hostname {host!r} resolves to a non-public address ({raw})."
            )

    return url


def _is_disallowed_ip(ip):
    """Return True for private / loopback / link-local / reserved / multicast.

    ``ipaddress`` covers most of what we care about via the ``is_*``
    properties. We deliberately reject *all* non-globally-routable
    space rather than a curated denylist — anything that isn't a
    public unicast address has no business being a webhook target.
    """
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


# Cloud metadata endpoints — the concrete SSRF prize. AWS/Azure/GCP all
# share ``169.254.169.254`` on the link-local range; Alibaba uses
# ``100.100.100.200``. Their IPv6 counterparts on some platforms sit
# under fd00:ec2::. Kept as strings so we can compare against parsed
# hostname / IP without materialising ``ipaddress`` for every match.
_CLOUD_METADATA_HOSTS = frozenset({
    '169.254.169.254',           # AWS / Azure / GCP IMDS
    'fd00:ec2::254',             # AWS EC2 IPv6
    '100.100.100.200',           # Alibaba Cloud ECS
    'metadata.google.internal',  # GCP DNS alias
})


def validate_internal_url_no_metadata(url: str) -> str:
    """Weaker sibling of :func:`validate_public_url` — allows private
    ranges (so admins can point Ollama at ``http://localhost:11434`` or
    an intra-cluster service DNS name) but still rejects cloud-metadata
    endpoints, which are the concrete SSRF prize an attacker actually
    wants.

    Use case: admin-only probe endpoints where the destination is
    legitimately expected to be inside the operator's network. The
    probe MUST NOT be used by non-admin users; this helper is not a
    substitute for the stronger :func:`validate_public_url` on
    user-supplied webhook URLs.

    Accepts http/https. Rejects file://, gopher://, and other exotic
    schemes that the ``requests`` library would happily follow.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL is required.")

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        raise ValueError("URL must start with http:// or https://")

    host = parsed.hostname
    if not host:
        raise ValueError("URL has no hostname.")

    if host.lower() in _CLOUD_METADATA_HOSTS:
        raise ValueError(
            f"URL points at a cloud metadata endpoint ({host}) — refused."
        )

    # Also block hostnames that resolve to a metadata IP (e.g. a DNS
    # trick pointing my-ollama.example.com → 169.254.169.254).
    try:
        addrinfo = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Resolution failure is not a security issue — the actual
        # request will fail with the same error. Let it through.
        return url

    for ai in addrinfo:
        ip_str = ai[4][0]
        if ip_str in _CLOUD_METADATA_HOSTS:
            raise ValueError(
                f"Hostname {host!r} resolves to metadata IP {ip_str} — refused."
            )

    return url
