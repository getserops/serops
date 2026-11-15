"""System checks for SerOps Enterprise (run by ``manage.py check`` and at startup)."""
from django.conf import settings
from django.core.checks import Warning, register


@register()
def saml_urls(app_configs, **kwargs):
    """The SAML entity ID and ACS URL are built from API_URL, which must end in /api.

    Without it the URLs given to the identity provider point outside the API
    and every SAML sign-in lands on a 404.
    """
    api_url = (getattr(settings, 'API_URL', None) or '').rstrip('/')
    if api_url and not api_url.endswith('/api'):
        return [Warning(
            f'API_URL ({api_url}) does not end in /api: SAML sign-in URLs would point outside the API.',
            hint='Set API_URL to the public URL followed by /api, e.g. https://serops.example.com/api.',
            id='ee.W001')]
    return []
