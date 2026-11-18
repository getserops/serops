"""A hostile Flux revision string cannot make the SHA parsing slow."""
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

    def test_long_runs_of_zeros_return_quickly(self):
        start = time.monotonic()
        for revision in ('0' * 200_000, '0:' + '0' * 200_000, '@' * 200_000):
            FluxDeploymentWebhookHandler._extract_sha(revision)
        self.assertLess(time.monotonic() - start, 0.5)

    def test_same_results_as_the_former_regex(self):
        import re
        former = re.compile(r'[a-z0-9]+:([a-fA-F0-9]{7,64})')
        cases = [
            '', 'main', 'main@sha1:abc', 'main@sha1:abcdef1', 'main@SHA1:' + 'a' * 40,
            'sha1:' + 'f' * 70, 'main@sha1:' + 'a' * 40 + 'zz', 'v1@sha256:' + 'B' * 64,
            'a@b@sha1:' + '1' * 12, 'main@:' + 'a' * 40, 'main@sha-1:' + 'a' * 40,
            'main@sha1:g' + 'a' * 40, 'main/sha1:' + 'a' * 12,
        ]
        for revision in cases:
            m = former.match(revision.rsplit('@', 1)[-1])
            expected = m.group(1) if m else ''
            self.assertEqual(FluxDeploymentWebhookHandler._extract_sha(revision), expected, revision)
