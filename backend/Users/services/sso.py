import logging
from hmac import compare_digest

from authlib.integrations.requests_client import OAuth2Session

logger = logging.getLogger(__name__)


def _guarded_oauth_session(*args, **kwargs):
    """An Authlib ``OAuth2Session`` (a ``requests.Session``) with the outbound
    policy of ``Utils.outbound.GuardedSession``: the token endpoint is checked,
    resolved once and connected to a checked address, and only same-origin
    redirects are followed (audit 2026-11-20, item 3)."""
    import types
    from urllib.parse import urljoin
    from Utils.outbound import MAX_REDIRECTS, PinnedAdapter, _origin

    client = OAuth2Session(*args, **kwargs)
    base_target = client.get_redirect_target

    def get_redirect_target(self, resp):
        target = base_target(resp)
        if target and _origin(urljoin(resp.url, target)) != _origin(resp.url):
            return None
        return target

    client.get_redirect_target = types.MethodType(get_redirect_target, client)
    client.max_redirects = MAX_REDIRECTS
    adapter = PinnedAdapter()
    client.mount('http://', adapter)
    client.mount('https://', adapter)
    return client

class SSOService:
    def __init__(self, client_id, client_secret, discovery_url, redirect_uri, extra_scopes=''):
        self.client_id = client_id
        self.scope = ' '.join(dict.fromkeys(['openid', 'email', 'profile', *(extra_scopes or '').split()]))
        self.client_secret = client_secret
        self.discovery_url = discovery_url
        self.redirect_uri = redirect_uri
        self.metadata = None

    def _fetch_metadata(self):
        """Fetch OIDC metadata from the discovery URL"""
        if not self.metadata:
            try:
                # Guarded: the discovery URL is admin-configured and the
                # request used to follow any redirect, with no timeout
                # (security review 2026-11, finding 3).
                from Utils.outbound import GuardedSession
                response = GuardedSession().get(self.discovery_url, timeout=10)
                response.raise_for_status()
                self.metadata = response.json()
            except Exception as e:
                logger.error(f"Failed to fetch OIDC metadata: {e}")
                raise

    def get_authorization_url(self, state, nonce, code_verifier):
        """Generate the OIDC authorization URL"""
        self._fetch_metadata()
        authorization_endpoint = self.metadata.get('authorization_endpoint')
        
        client = OAuth2Session(
            self.client_id, 
            self.client_secret, 
            scope=self.scope,
            redirect_uri=self.redirect_uri,
            code_challenge_method='S256',
        )

        uri, state = client.create_authorization_url(
            authorization_endpoint, state=state, nonce=nonce, code_verifier=code_verifier)
        return uri, state

    def exchange_code_for_token(self, code, code_verifier):
        """Exchange the authorization code for access details"""
        self._fetch_metadata()
        token_endpoint = self.metadata.get('token_endpoint')
        # The endpoints come from the identity provider's metadata, so they
        # get the same check as the discovery URL.
        from Utils.outbound import check_url
        check_url(token_endpoint)
        
        client = _guarded_oauth_session(
            self.client_id,
            self.client_secret,
            redirect_uri=self.redirect_uri
        )
        
        token = client.fetch_token(
            token_endpoint, 
            code=code, 
            grant_type='authorization_code',
            code_verifier=code_verifier,
        )
        return token

    # Seconds of clock difference tolerated on ``exp``.
    CLOCK_SKEW_SECONDS = 120

    def _id_token_claims(self, token):
        import jwt
        try:
            return jwt.decode(token.get('id_token') or '', options={'verify_signature': False})
        except jwt.InvalidTokenError:
            return None

    def _expected_issuer(self, claims):
        """The issuer from the provider's metadata. Entra's multi-tenant
        metadata gives ``https://login.microsoftonline.com/{tenantid}/v2.0``:
        the template is filled with the token's own ``tid``."""
        issuer = (self.metadata or {}).get('issuer') or ''
        if '{tenantid}' in issuer:
            tid = str(claims.get('tid') or '')
            if not tid:
                return ''
            issuer = issuer.replace('{tenantid}', tid)
        return issuer

    def id_token_matches(self, token, nonce):
        """Whether the ID token was issued to us, by this provider, for the flow
        this browser started, and has not expired.

        The signature is not checked: the token came straight from the token
        endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts instead.
        ``iss`` and ``exp`` are (audit 2026-11-20, item 4).
        """
        import time
        claims = self._id_token_claims(token)
        if claims is None:
            return False
        audience = claims.get('aud')
        audiences = audience if isinstance(audience, list) else [audience]
        if not (compare_digest(str(claims.get('nonce') or ''), nonce) and self.client_id in audiences):
            return False
        try:
            expires = float(claims.get('exp'))
        except (TypeError, ValueError):
            return False
        if expires + self.CLOCK_SKEW_SECONDS < time.time():
            return False
        expected = self._expected_issuer(claims)
        return bool(expected) and compare_digest(str(claims.get('iss') or ''), expected)

    def user_info_matches(self, token, user_info):
        """The userinfo answer is about the user the ID token names (OpenID
        Connect Core 5.3.2: the ``sub`` values must be equal)."""
        claims = self._id_token_claims(token) or {}
        sub = str(claims.get('sub') or '')
        return bool(sub) and compare_digest(str((user_info or {}).get('sub') or ''), sub)

    def get_user_info(self, token):
        """Fetch user info using the access token"""
        self._fetch_metadata()
        userinfo_endpoint = self.metadata.get('userinfo_endpoint')
        
        from Utils.outbound import GuardedSession
        headers = {'Authorization': f"Bearer {token['access_token']}"}
        response = GuardedSession().get(userinfo_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
