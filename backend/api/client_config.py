"""Settings the web app reads before login (``/api/client-config/``).

Usage counting is for an operator's public demo instance and is off by
default: with ``SEROPS_USAGE_SCRIPT_PATH`` and ``SEROPS_USAGE_WEBSITE_ID``
unset, the answer is ``{"usage": null}`` and the app loads nothing.

The script must come from the instance's own origin (a path the operator's
reverse proxy serves), so the app's Content-Security-Policy stays
``script-src 'self'`` and a setting can never point a browser at another
site. Anything else is ignored rather than passed on.
"""
import re

from django.conf import settings

_SCRIPT_PATH = re.compile(r'^/(?!/)[A-Za-z0-9._/-]{1,200}\.js$')
_WEBSITE_ID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


def usage_config():
    path = getattr(settings, 'SEROPS_USAGE_SCRIPT_PATH', '') or ''
    website_id = getattr(settings, 'SEROPS_USAGE_WEBSITE_ID', '') or ''
    if not path or not website_id:
        return None
    if not _SCRIPT_PATH.match(path) or '..' in path or not _WEBSITE_ID.match(website_id):
        return None
    return {'script_path': path, 'website_id': website_id.lower()}


def client_config() -> dict:
    return {'usage': usage_config()}
