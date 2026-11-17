"""A hostile Flux revision string cannot make the SHA regex slow."""
import time

from django.test import SimpleTestCase

from providers.flux_webhook import FluxDeploymentWebhookHandler


class FluxRevisionRedosTest(SimpleTestCase):

    def test_normal_revisions_still_parse(self):
        sha = 'a' * 40
        self.assertEqual(FluxDeploymentWebhookHandler._extract_sha(f'main@sha1:{sha}'), sha)
        self.assertEqual(FluxDeploymentWebhookHandler._extract_sha(f'main@sha256:{"b" * 64}'), 'b' * 64)

    def test_a_long_hostile_revision_returns_quickly(self):
        start = time.monotonic()
        self.assertEqual(FluxDeploymentWebhookHandler._extract_sha('a' * 200_000), '')
        self.assertLess(time.monotonic() - start, 0.5)
