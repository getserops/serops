"""A project with a single environment also reads the logs that carry no
environment at all: they can only belong to it."""
from django.test import SimpleTestCase

from integrations.schemas import LogQuery


def query(untagged):
    return LogQuery(project="shop", environment="production", environment_untagged=untagged)


class UntaggedEnvironmentTest(SimpleTestCase):
    def test_elasticsearch(self):
        self.assertIn("must_not", str(query(True).to_es_dsl()))
        self.assertNotIn("must_not", str(query(False).to_es_dsl()))

    def test_loki_matches_streams_without_the_label(self):
        self.assertIn('environment=~"production|prod|prd|"', query(True).to_logql())
        self.assertIn('environment=~"production|prod|prd"', query(False).to_logql())

    def test_datadog(self):
        self.assertIn("-env:* -@env:*", query(True).to_datadog_query())
        self.assertNotIn("-env:*", query(False).to_datadog_query())

    def test_splunk(self):
        self.assertIn("NOT environment=*", query(True).to_splunk_spl())
        self.assertNotIn("NOT environment=*", query(False).to_splunk_spl())

    def test_azure(self):
        self.assertIn("isempty(tostring(Properties.environment))", query(True).to_azure_kql())
        self.assertNotIn("isempty", query(False).to_azure_kql())

    def test_gcp(self):
        self.assertIn("NOT labels.environment:*", query(True).to_gcp_filter())
        self.assertNotIn("NOT labels.environment", query(False).to_gcp_filter())
