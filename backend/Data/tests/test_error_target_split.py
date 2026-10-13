"""Tests for the ``error_target`` storage-vs-fingerprint split
(RCA audit finding #3, PR-AUDIT2).

Before this fix, ``normalize_error_target`` did double duty — it
collapsed volatile parts (ports, pids, uuids, 4+ digit numbers) into
``<id>`` / ``<uuid>`` placeholders so two errors from the same class
fingerprinted identically. The same normalised value was stored on
the Issue row, so an operator triaging an incident saw
``error_target='redis:<id>'`` instead of ``redis:6379`` — un-greppable.

Fix: the public ``normalize_error_target`` now does light
normalization only (trim + lowercase + path strip). The private
``_signature_normalize_error_target`` does the aggressive form for
fingerprint hashing so dedup still collapses same-class errors.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from Data.models import Issue


class LightNormalizerPreservesLiteralsTest(SimpleTestCase):
    """The stored ``error_target`` must keep the literal so an
    operator can grep, click through to a Grafana dashboard, or paste
    the value into a Slack thread and have it mean the same thing."""

    def test_port_literal_preserved(self):
        self.assertEqual(
            Issue.normalize_error_target("redis:6379"),
            "redis:6379",
        )

    def test_high_port_literal_preserved(self):
        self.assertEqual(
            Issue.normalize_error_target("postgres:5432"),
            "postgres:5432",
        )

    def test_pid_literal_preserved(self):
        # Real pids run into the thousands; the old normaliser turned
        # "pid 2847" into "pid <id>" — this fix keeps the number.
        self.assertEqual(
            Issue.normalize_error_target("python (pid 2847)"),
            "python (pid 2847)",
        )

    def test_uuid_literal_preserved(self):
        # An operator staring at a failing session id needs the
        # actual UUID to find the session in the database.
        self.assertEqual(
            Issue.normalize_error_target(
                "session-4d3c2b1a-1234-5678-9abc-def012345678"
            ),
            "session-4d3c2b1a-1234-5678-9abc-def012345678",
        )

    def test_light_normalization_still_applies(self):
        # Trim + lowercase + path strip — expected to still happen.
        self.assertEqual(
            Issue.normalize_error_target(
                "  /var/log/services/CHECKOUT.log  "
            ),
            "checkout.log",
        )

    def test_empty_input_still_returns_empty(self):
        self.assertEqual(Issue.normalize_error_target(""), "")
        self.assertEqual(Issue.normalize_error_target(None), "")


class SignatureNormalizerStillCollapsesTest(SimpleTestCase):
    """The fingerprint side of the split still collapses volatile
    identifiers so ``redis:6379`` and ``redis:6380`` dedup as one issue."""

    def test_ports_collapse_for_fingerprint(self):
        self.assertEqual(
            Issue._signature_normalize_error_target("redis:6379"),
            Issue._signature_normalize_error_target("redis:6380"),
        )
        self.assertEqual(
            Issue._signature_normalize_error_target("redis:6379"),
            "redis:<id>",
        )

    def test_uuids_collapse_for_fingerprint(self):
        a = Issue._signature_normalize_error_target(
            "session-4d3c2b1a-1234-5678-9abc-def012345678"
        )
        b = Issue._signature_normalize_error_target(
            "session-11111111-2222-3333-4444-555555555555"
        )
        self.assertEqual(a, b)
        self.assertIn("<uuid>", a)

    def test_pids_collapse_for_fingerprint(self):
        self.assertEqual(
            Issue._signature_normalize_error_target("python (pid 2847)"),
            Issue._signature_normalize_error_target("python (pid 8123)"),
        )


class FingerprintCollapsesButStoresLiteralTest(SimpleTestCase):
    """The end-to-end promise: two events with different ports share
    a fingerprint (so dedup works) but each row stores its own port."""

    def test_two_ports_share_fingerprint(self):
        fp_a = Issue.generate_fingerprint(
            "CONNECTION_REFUSED", "SERVICE", "myproj", "checkout",
            environment="production", error_class="CONNECTION_REFUSED",
            error_target="redis:6379",
        )
        fp_b = Issue.generate_fingerprint(
            "CONNECTION_REFUSED", "SERVICE", "myproj", "checkout",
            environment="production", error_class="CONNECTION_REFUSED",
            error_target="redis:6380",
        )
        self.assertEqual(fp_a, fp_b)

    def test_storage_normalizer_keeps_original_port(self):
        # And the value that would land on Issue.error_target still
        # reads as the actual literal.
        stored = Issue.normalize_error_target("redis:6379")
        self.assertEqual(stored, "redis:6379")
        self.assertNotIn("<id>", stored)
