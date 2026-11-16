"""log_service reads the service under every name a store uses, not only
``service_name`` (phase 3 review: Elasticsearch, Datadog and Fluent Bit logs
were dropped from scheduled analyses as "unregistered service")."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from Data.log_filters import log_service


def hit(source):
    return {'_source': source}


class LogServiceAliasesTests(SimpleTestCase):
    def test_canonical_field(self):
        self.assertEqual(log_service(hit({'service_name': 'Checkout'})), 'checkout')

    def test_legacy_dict_service_field(self):
        # to_legacy_dict() always writes ``service``
        self.assertEqual(log_service(hit({'service': 'cart'})), 'cart')

    def test_otel_dotted_and_nested(self):
        self.assertEqual(log_service(hit({'service.name': 'payment'})), 'payment')
        self.assertEqual(log_service(hit({'service': {'name': 'payment'}})), 'payment')

    def test_kubernetes_labels(self):
        self.assertEqual(log_service(hit({'kubernetes': {'labels': {'app': 'Frontend'}}})), 'frontend')

    def test_canonical_wins_over_alias(self):
        self.assertEqual(log_service(hit({'service_name': 'a', 'service': 'b'})), 'a')

    def test_empty_canonical_does_not_shadow_alias(self):
        self.assertEqual(log_service(hit({'service_name': '', 'app': 'api'})), 'api')

    def test_none(self):
        self.assertEqual(log_service(hit({'message': 'x'})), '')
        self.assertEqual(log_service({}), '')

    def test_log_entry_object(self):
        self.assertEqual(log_service(SimpleNamespace(service='Ads')), 'ads')
        self.assertEqual(log_service(SimpleNamespace(service=None)), '')
