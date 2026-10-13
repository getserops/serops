"""Tests for the version endpoint (Batch 43).

Every mature self-hosted OSS exposes a version endpoint so users
filing support tickets don't need to shell into the container. These
tests lock in the contract: no auth, stable JSON keys, env-var
override wins.
"""

import os
from unittest import mock

from django.test import TestCase
from django.urls import reverse


class VersionEndpointTest(TestCase):
    """Uses TestCase (not SimpleTestCase) because the request path hits
    the QueryTimeoutMiddleware which touches the DB connection."""

    def test_endpoint_is_public(self):
        """No auth header required — this is a support / discovery endpoint."""
        resp = self.client.get(reverse('version'))
        self.assertEqual(resp.status_code, 200)

    def test_returns_stable_json_keys(self):
        """Contract: 'version', 'git_sha', 'built_at' — support tooling parses these."""
        resp = self.client.get(reverse('version'))
        body = resp.json()
        self.assertIn('version', body)
        self.assertIn('git_sha', body)
        self.assertIn('built_at', body)

    def test_default_version_is_dev_fallback(self):
        """Without SEROPS_VERSION set, we serve the dev fallback."""
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SEROPS_VERSION', None)
            # Re-import so the module picks up the fresh env.
            import importlib
            from api import version as v_mod
            importlib.reload(v_mod)
            resp = self.client.get(reverse('version'))
            self.assertEqual(resp.json()['version'], '1.0.0-dev')
            # Restore to avoid leaking to other tests.
            importlib.reload(v_mod)

    def test_env_override_wins(self):
        """CI stamps SEROPS_VERSION at image build time."""
        with mock.patch.dict(os.environ, {'SEROPS_VERSION': '1.2.3'}):
            import importlib
            from api import version as v_mod
            importlib.reload(v_mod)
            resp = self.client.get(reverse('version'))
            self.assertEqual(resp.json()['version'], '1.2.3')
            importlib.reload(v_mod)

    def test_git_sha_truncated_to_seven(self):
        """Full SHA in env, 7-char short SHA in response."""
        long_sha = 'abcdef1234567890abcdef1234567890abcdef12'
        with mock.patch.dict(os.environ, {'SEROPS_GIT_SHA': long_sha}):
            import importlib
            from api import version as v_mod
            importlib.reload(v_mod)
            from api.version import version_info
            self.assertEqual(version_info()['git_sha'], long_sha[:7])
