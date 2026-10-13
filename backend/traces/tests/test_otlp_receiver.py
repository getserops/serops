"""Tests for the OTLP HTTP traces receiver + IngestKey model.

Covers:

Models
  * IngestKey.generate_key / hash_key / verify — plaintext round-trip
  * verify() rejects wrong prefix / wrong hash / inactive key
  * set_key populates hash + prefix correctly

OTLP receiver
  * Missing / malformed / wrong Bearer → 401
  * Valid Bearer → 200, spans + traces persisted
  * Multiple resourceSpans → all ingested
  * Trace rollup: span_count, error_span_count, status_code, root_service
  * Resource-level service.name inherited by spans
  * Alias support: `service` (Datadog USM) → service_name
  * Duplicate span (retry) → ignore_conflicts, no crash
  * Malformed span (bad trace_id length) → skipped, other spans succeed

IngestKey CRUD
  * List returns caller's org keys only
  * Create returns plaintext ONCE
  * Delete is soft (is_active=False, row survives)
  * Non-admin cannot create / delete

Security
  * Plaintext never appears in read responses
  * Cross-org key cannot be deleted (404)
  * Wrong-hash key never authenticates (constant-time compare)
"""

import gzip
import json
import zlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from Organisations.models import Organisations
from traces.models import IngestKey, Span, Trace

User = get_user_model()


# ============================================================================
# Model — IngestKey semantics
# ============================================================================


class IngestKeyModelTest(TestCase):
    def setUp(self):
        self.org = Organisations.objects.create(name='IngestKeyOrg')

    def test_generate_key_shape(self):
        plaintext = IngestKey.generate_key()
        self.assertTrue(plaintext.startswith('serops_otlp_'))
        # Body = 32 bytes → url-safe base64 → 43 chars (no padding).
        self.assertGreaterEqual(len(plaintext), len('serops_otlp_') + 40)

    def test_hash_key_deterministic(self):
        h1 = IngestKey.hash_key('serops_otlp_xyz')
        h2 = IngestKey.hash_key('serops_otlp_xyz')
        self.assertEqual(h1, h2)
        self.assertNotEqual(h1, IngestKey.hash_key('serops_otlp_other'))
        # SHA-256 hex is 64 chars.
        self.assertEqual(len(h1), 64)

    def test_set_key_populates_hash_and_prefix(self):
        key = IngestKey(organisation=self.org, name='test')
        plaintext = IngestKey.generate_key()
        key.set_key(plaintext)
        key.save()
        self.assertEqual(key.key_hash, IngestKey.hash_key(plaintext))
        # Prefix is a truncated PREFIX (identification), not enough to reconstruct.
        self.assertTrue(plaintext.startswith(key.key_prefix))
        self.assertLess(len(key.key_prefix), len(plaintext))

    def test_verify_returns_active_row(self):
        plaintext = IngestKey.generate_key()
        row = IngestKey(organisation=self.org, name='k')
        row.set_key(plaintext)
        row.save()
        found = IngestKey.verify(plaintext)
        self.assertEqual(found.pk, row.pk)

    def test_verify_rejects_wrong_key(self):
        plaintext = IngestKey.generate_key()
        row = IngestKey(organisation=self.org, name='k')
        row.set_key(plaintext)
        row.save()
        self.assertIsNone(IngestKey.verify(IngestKey.generate_key()))

    def test_verify_rejects_missing_prefix(self):
        # Non-serops-prefixed keys are never valid.
        self.assertIsNone(IngestKey.verify('not_a_serops_key'))

    def test_verify_rejects_inactive_key(self):
        plaintext = IngestKey.generate_key()
        row = IngestKey(organisation=self.org, name='k')
        row.set_key(plaintext)
        row.is_active = False
        row.save()
        self.assertIsNone(IngestKey.verify(plaintext))

    def test_verify_rejects_empty(self):
        self.assertIsNone(IngestKey.verify(''))
        self.assertIsNone(IngestKey.verify(None))


# ============================================================================
# OTLP receiver — payload ingest
# ============================================================================


class OtlpReceiverBase(TestCase):
    """Base with org + ingest key + client + payload builders."""

    def setUp(self):
        self.org = Organisations.objects.create(name='OtlpOrg')
        self.plaintext = IngestKey.generate_key()
        self.key = IngestKey(organisation=self.org, name='test-collector')
        self.key.set_key(self.plaintext)
        self.key.save()
        self.client = APIClient()
        self.url = '/api/traces/v1/traces'

    def _post(self, payload, auth=None):
        auth = auth if auth is not None else self.plaintext
        headers = {'HTTP_AUTHORIZATION': f'Bearer {auth}'} if auth else {}
        return self.client.post(
            self.url, data=json.dumps(payload),
            content_type='application/json', **headers,
        )

    def _payload(self, trace_id='a' * 32, spans=None, service_name='checkout'):
        """Build a minimal OTLP resourceSpans payload."""
        default_span = {
            'traceId': trace_id,
            'spanId': 'b' * 16,
            'parentSpanId': '',
            'name': 'GET /api/checkout',
            'kind': 'SPAN_KIND_SERVER',
            'startTimeUnixNano': '1730000000000000000',
            'endTimeUnixNano': '1730000000123000000',   # 123 ms
            'attributes': [],
            'status': {'code': 'STATUS_CODE_OK'},
        }
        return {
            'resourceSpans': [{
                'resource': {
                    'attributes': [
                        {'key': 'service.name', 'value': {'stringValue': service_name}},
                        {'key': 'deployment.environment', 'value': {'stringValue': 'production'}},
                    ],
                },
                'scopeSpans': [{'spans': spans if spans is not None else [default_span]}],
            }],
        }


class OtlpAuthTest(OtlpReceiverBase):

    def test_missing_authorization_401(self):
        response = self._post(self._payload(), auth='')
        self.assertEqual(response.status_code, 401)

    def test_wrong_bearer_401(self):
        response = self._post(self._payload(), auth='serops_otlp_wrong_key')
        self.assertEqual(response.status_code, 401)

    def test_wrong_prefix_401(self):
        response = self._post(self._payload(), auth='ghp_notaseropskey')
        self.assertEqual(response.status_code, 401)

    def test_inactive_key_401(self):
        self.key.is_active = False
        self.key.save()
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 401)


class OtlpIngestTest(OtlpReceiverBase):

    def test_valid_payload_returns_counts(self):
        response = self._post(self._payload())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['accepted_spans'], 1)
        self.assertEqual(data['accepted_traces'], 1)

    def test_span_and_trace_persisted(self):
        self._post(self._payload())
        self.assertEqual(Span.objects.count(), 1)
        self.assertEqual(Trace.objects.count(), 1)
        trace = Trace.objects.first()
        self.assertEqual(trace.organisation, self.org)
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.status_code, 'OK')
        self.assertEqual(trace.span_count, 1)
        self.assertEqual(trace.error_span_count, 0)
        self.assertEqual(trace.duration_ms, 123)

    def test_service_name_from_resource_inherited(self):
        # Span has no service.name attribute — should inherit resource-level.
        response = self._post(self._payload(service_name='api'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Span.objects.first().service_name, 'api')

    def test_service_alias_at_resource_level(self):
        """Datadog USM `service` (not `service.name`) works via alias support."""
        payload = self._payload()
        payload['resourceSpans'][0]['resource']['attributes'] = [
            {'key': 'service', 'value': {'stringValue': 'aliased-service'}},
        ]
        response = self._post(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Span.objects.first().service_name, 'aliased-service')

    def test_error_span_updates_trace_status(self):
        error_span = {
            'traceId': 'a' * 32,
            'spanId': 'c' * 16,
            'parentSpanId': '',
            'name': 'GET /api/broken',
            'kind': 'SPAN_KIND_SERVER',
            'startTimeUnixNano': '1730000000000000000',
            'endTimeUnixNano': '1730000000200000000',
            'attributes': [],
            'status': {'code': 'STATUS_CODE_ERROR', 'message': 'boom'},
        }
        self._post(self._payload(spans=[error_span]))
        trace = Trace.objects.first()
        self.assertEqual(trace.status_code, 'ERROR')
        self.assertEqual(trace.error_span_count, 1)
        span = Span.objects.first()
        self.assertEqual(span.status_code, 'ERROR')
        self.assertEqual(span.status_message, 'boom')

    def test_duplicate_span_ignored(self):
        """Retry-safety: same (trace_id, span_id) sent twice doesn't 500."""
        r1 = self._post(self._payload())
        r2 = self._post(self._payload())
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(Span.objects.count(), 1)

    def test_malformed_span_skipped_not_crashed(self):
        good_span = {
            'traceId': 'a' * 32,
            'spanId': 'b' * 16,
            'parentSpanId': '',
            'name': 'good',
            'startTimeUnixNano': '1730000000000000000',
            'endTimeUnixNano': '1730000000050000000',
            'attributes': [],
            'status': {'code': 'STATUS_CODE_OK'},
        }
        bad_span = {
            'traceId': 'short',   # length 5, not 32 — must be dropped
            'spanId': 'x' * 16,
            'startTimeUnixNano': '1730000000000000000',
            'endTimeUnixNano': '1730000000050000000',
        }
        response = self._post(self._payload(spans=[good_span, bad_span]))
        self.assertEqual(response.status_code, 200)
        # Only the good span was persisted.
        self.assertEqual(Span.objects.count(), 1)

    def test_events_stored_as_json(self):
        span_with_event = {
            'traceId': 'a' * 32,
            'spanId': 'b' * 16,
            'parentSpanId': '',
            'name': 'op',
            'startTimeUnixNano': '1730000000000000000',
            'endTimeUnixNano': '1730000000050000000',
            'attributes': [],
            'status': {'code': 'STATUS_CODE_OK'},
            'events': [{
                'timeUnixNano': '1730000000010000000',
                'name': 'exception',
                'attributes': [
                    {'key': 'exception.type', 'value': {'stringValue': 'ValueError'}},
                ],
            }],
        }
        self._post(self._payload(spans=[span_with_event]))
        span = Span.objects.first()
        self.assertEqual(len(span.events), 1)
        self.assertEqual(span.events[0]['name'], 'exception')
        self.assertEqual(
            span.events[0]['attributes']['exception.type'], 'ValueError',
        )


# ============================================================================
# IngestKey CRUD API
# ============================================================================


class IngestKeyCrudTest(TestCase):

    def setUp(self):
        self.org = Organisations.objects.create(name='CrudOrg')
        self.other_org = Organisations.objects.create(name='OtherOrg')
        self.admin = User.objects.create_user(
            username='admin', email='a@t.com', password='p',
            organisation=self.org, role='admin', is_active=True,
        )
        self.member = User.objects.create_user(
            username='member', email='m@t.com', password='p',
            organisation=self.org, role='user', is_active=True,
        )
        self.client = APIClient()
        self.url = '/api/traces/keys/'

    def _make_key(self, org, name):
        row = IngestKey(organisation=org, name=name)
        row.set_key(IngestKey.generate_key())
        row.save()
        return row

    def test_admin_can_list_own_org_keys(self):
        self._make_key(self.org, 'k1')
        self._make_key(self.other_org, 'other')
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        names = [k['name'] for k in response.json()]
        self.assertIn('k1', names)
        self.assertNotIn('other', names)

    def test_non_admin_cannot_list(self):
        self.client.force_authenticate(user=self.member)
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_create_returns_plaintext_once(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.url, {'name': 'test'}, format='json')
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIn('plaintext', data)
        self.assertTrue(data['plaintext'].startswith('serops_otlp_'))
        # Subsequent LIST does NOT include plaintext.
        list_response = self.client.get(self.url).json()
        self.assertNotIn('plaintext', list_response[0])

    def test_created_key_authenticates_otlp(self):
        self.client.force_authenticate(user=self.admin)
        create = self.client.post(self.url, {'name': 'test'}, format='json')
        plaintext = create.json()['plaintext']
        # Fresh client (no auth) hitting OTLP with the returned key.
        anon = APIClient()
        payload = {'resourceSpans': []}
        response = anon.post(
            '/api/traces/v1/traces',
            data=json.dumps(payload), content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {plaintext}',
        )
        self.assertEqual(response.status_code, 200)

    def test_delete_is_soft_delete(self):
        key = IngestKey(organisation=self.org, name='del')
        key.set_key(IngestKey.generate_key())
        key.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f'{self.url}{key.pk}/')
        self.assertEqual(response.status_code, 204)
        # Row still exists, is_active=False.
        key.refresh_from_db()
        self.assertFalse(key.is_active)

    def test_cannot_delete_other_orgs_key(self):
        stranger_key = IngestKey(organisation=self.other_org, name='foreign')
        stranger_key.set_key(IngestKey.generate_key())
        stranger_key.save()
        self.client.force_authenticate(user=self.admin)
        response = self.client.delete(f'{self.url}{stranger_key.pk}/')
        self.assertEqual(response.status_code, 404)
        # And the key is NOT touched.
        stranger_key.refresh_from_db()
        self.assertTrue(stranger_key.is_active)


# ============================================================================
# Content-Encoding — the OTel Collector gzips by DEFAULT
# ============================================================================


class OTLPCompressionTest(TestCase):
    """The otlphttp exporter compresses with gzip unless told otherwise, and
    Django does not decompress request bodies (GZipMiddleware only handles
    responses). So a default-configured collector had its entire payload
    rejected: protobuf ParseFromString saw gzip bytes, failed, and the
    receiver answered 400.

    Verified against a real collector on Kubernetes — 48 spans dropped with
    the default config, the same traffic ingesting fine with
    `compression: none`. These tests pin the default working.
    """

    URL = '/api/traces/v1/traces'

    def setUp(self):
        self.client = APIClient()
        self.org = Organisations.objects.create(name='Compression Org')
        self.plaintext = IngestKey.generate_key()
        key = IngestKey(organisation=self.org, name='collector')
        key.set_key(self.plaintext)
        key.save()
        self.auth = f'Bearer {self.plaintext}'

    def _payload(self, trace_id='aabbccddeeff00112233445566778899'):
        return {
            'resourceSpans': [{
                'resource': {'attributes': [
                    {'key': 'service.name', 'value': {'stringValue': 'checkout'}},
                ]},
                'scopeSpans': [{'spans': [{
                    'traceId': trace_id,
                    'spanId': '1122334455667788',
                    'name': 'POST /checkout',
                    'kind': 2,
                    'startTimeUnixNano': '1790000000000000000',
                    'endTimeUnixNano': '1790000000500000000',
                }]}],
            }],
        }

    def _post(self, body, **extra):
        return self.client.post(
            self.URL, data=body, content_type='application/json',
            HTTP_AUTHORIZATION=self.auth, **extra,
        )

    # -- gzip, the collector default ----------------------------------

    def test_gzip_json_is_accepted(self):
        body = gzip.compress(json.dumps(self._payload()).encode())
        resp = self._post(body, HTTP_CONTENT_ENCODING='gzip')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Span.objects.count(), 1)

    def test_gzip_actually_persists_the_span(self):
        body = gzip.compress(json.dumps(self._payload()).encode())
        self._post(body, HTTP_CONTENT_ENCODING='gzip')
        trace = Trace.objects.get()
        self.assertEqual(trace.root_service_name, 'checkout')
        self.assertEqual(trace.span_count, 1)

    def test_deflate_is_accepted(self):
        body = zlib.compress(json.dumps(self._payload()).encode())
        resp = self._post(body, HTTP_CONTENT_ENCODING='deflate')
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Span.objects.count(), 1)

    def test_identity_is_accepted(self):
        resp = self._post(
            json.dumps(self._payload()).encode(), HTTP_CONTENT_ENCODING='identity')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_uncompressed_still_works(self):
        """Regression guard — the path that worked before must keep working."""
        resp = self._post(json.dumps(self._payload()).encode())
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(Span.objects.count(), 1)

    # -- failure modes are distinguishable ----------------------------

    def test_unsupported_encoding_says_so(self):
        """zstd is in the OTLP spec but needs a third-party library. The
        operator should learn that, not see a generic 'malformed payload'."""
        resp = self._post(b'whatever', HTTP_CONTENT_ENCODING='zstd')
        self.assertEqual(resp.status_code, 415)
        self.assertIn('zstd', str(resp.data))

    def test_corrupt_gzip_reports_encoding_not_content(self):
        resp = self._post(b'not-actually-gzip', HTTP_CONTENT_ENCODING='gzip')
        self.assertEqual(resp.status_code, 415)
        self.assertIn('gzip', str(resp.data))

    def test_malformed_json_still_400(self):
        resp = self._post(b'{not json', HTTP_CONTENT_ENCODING='identity')
        self.assertEqual(resp.status_code, 400)

    def test_gzipped_malformed_json_is_400_not_415(self):
        """Decompression succeeded; the payload is the problem."""
        resp = self._post(gzip.compress(b'{not json'), HTTP_CONTENT_ENCODING='gzip')
        self.assertEqual(resp.status_code, 400)

    def test_encoding_is_case_insensitive(self):
        body = gzip.compress(json.dumps(self._payload()).encode())
        resp = self._post(body, HTTP_CONTENT_ENCODING='GZIP')
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_auth_still_enforced_under_compression(self):
        body = gzip.compress(json.dumps(self._payload()).encode())
        resp = self.client.post(
            self.URL, data=body, content_type='application/json',
            HTTP_CONTENT_ENCODING='gzip', HTTP_AUTHORIZATION='Bearer wrong',
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(Span.objects.count(), 0)
