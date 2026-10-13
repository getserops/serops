"""Accept a trailing slash on API routes that were declared without one.

SerOps' API paths are slashless (``/api/auth/login``), which is unusual — the
DRF convention, and what most clients and copied-from-docs snippets assume, is
a trailing slash. ``POST /api/auth/login/`` returned 404.

Django's ``APPEND_SLASH`` is no help: it only ever ADDS a slash to reach a
matching route, never strips one. And the failure is quiet in the worst place —
the login form, where a 404 with no usable body reads as "invalid credentials",
sending the user to re-type a password that was always right.

This engages ONLY on a response that is already a 404, and only when stripping
the trailing slash resolves to a real view. It cannot change the behaviour of
any request that works today.

Redirecting is deliberately avoided: a 301 turns a POST into a GET and drops
the body, so the request that most needs this — logging in — would arrive
without its credentials. The matched view is called directly instead, so the
method and body survive.
"""

import logging

from django.urls import Resolver404, resolve

logger = logging.getLogger(__name__)


class TrailingSlashFallbackMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        if response.status_code != 404:
            return response

        path = request.path_info
        if not path.endswith('/') or path == '/':
            return response

        stripped = path.rstrip('/')
        if not stripped:
            return response

        try:
            match = resolve(stripped)
        except Resolver404:
            return response

        logger.debug(
            'Trailing-slash fallback: %s -> %s (%s)',
            path, stripped, getattr(match.func, '__name__', match.func),
        )

        # Re-dispatch with the corrected path. Rewriting path_info keeps the
        # method, headers and body intact, which a redirect would not.
        request.path_info = stripped
        request.path = stripped
        result = match.func(request, *match.args, **match.kwargs)

        # DRF returns an unrendered Response. Calling the view directly skips
        # the handler step that would normally render it, so the middleware
        # that runs after this one raises ContentNotRenderedError the moment it
        # touches .content. Render it here, as the handler would.
        if hasattr(result, 'render') and callable(result.render) \
                and not getattr(result, 'is_rendered', True):
            result = result.render()

        return result
