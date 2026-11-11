import logging
from hmac import compare_digest

from authlib.integrations.requests_client import OAuth2Session

logger = logging.getLogger(__name__)

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
        
        client = OAuth2Session(
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

    def id_token_matches(self, token, nonce):
        """Whether the ID token was issued to us, for the flow this browser started.

        The signature is not checked: the token came straight from the token
        endpoint over TLS, which OpenID Connect Core 3.1.3.7 accepts instead.
        """
        import jwt
        try:
            claims = jwt.decode(token.get('id_token') or '', options={'verify_signature': False})
        except jwt.InvalidTokenError:
            return False
        audience = claims.get('aud')
        audiences = audience if isinstance(audience, list) else [audience]
        return compare_digest(str(claims.get('nonce') or ''), nonce) and self.client_id in audiences

    def get_user_info(self, token):
        """Fetch user info using the access token"""
        self._fetch_metadata()
        userinfo_endpoint = self.metadata.get('userinfo_endpoint')
        
        from Utils.outbound import GuardedSession
        headers = {'Authorization': f"Bearer {token['access_token']}"}
        response = GuardedSession().get(userinfo_endpoint, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
