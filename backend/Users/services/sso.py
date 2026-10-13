import logging
from authlib.integrations.requests_client import OAuth2Session

logger = logging.getLogger(__name__)

class SSOService:
    def __init__(self, client_id, client_secret, discovery_url, redirect_uri):
        self.client_id = client_id
        self.client_secret = client_secret
        self.discovery_url = discovery_url
        self.redirect_uri = redirect_uri
        self.metadata = None

    def _fetch_metadata(self):
        """Fetch OIDC metadata from the discovery URL"""
        if not self.metadata:
            try:
                import requests
                response = requests.get(self.discovery_url)
                response.raise_for_status()
                self.metadata = response.json()
            except Exception as e:
                logger.error(f"Failed to fetch OIDC metadata: {e}")
                raise

    def get_authorization_url(self, state=None):
        """Generate the OIDC authorization URL"""
        self._fetch_metadata()
        authorization_endpoint = self.metadata.get('authorization_endpoint')
        
        client = OAuth2Session(
            self.client_id, 
            self.client_secret, 
            scope='openid email profile',
            redirect_uri=self.redirect_uri
        )
        
        uri, state = client.create_authorization_url(authorization_endpoint, state=state)
        return uri, state

    def exchange_code_for_token(self, code):
        """Exchange the authorization code for access details"""
        self._fetch_metadata()
        token_endpoint = self.metadata.get('token_endpoint')
        
        client = OAuth2Session(
            self.client_id, 
            self.client_secret, 
            redirect_uri=self.redirect_uri
        )
        
        token = client.fetch_token(
            token_endpoint, 
            code=code, 
            grant_type='authorization_code'
        )
        return token

    def get_user_info(self, token):
        """Fetch user info using the access token"""
        self._fetch_metadata()
        userinfo_endpoint = self.metadata.get('userinfo_endpoint')
        
        import requests
        headers = {'Authorization': f"Bearer {token['access_token']}"}
        response = requests.get(userinfo_endpoint, headers=headers)
        response.raise_for_status()
        return response.json()
