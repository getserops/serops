"""Phase C: every provider's query matches the project name OR any project log rule."""
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import SimpleTestCase

from integrations.adapters.loki import LokiLogProvider
from integrations.schemas import LogEntry, LogQuery

NOW = datetime.now(timezone.utc)
RULES = [('service.namespace', 'shop'), ('kubernetes.namespace', 'shop-prod')]


def query(**kw):
    return LogQuery(project='shop', project_rules=RULES, time_range=(NOW - timedelta(minutes=5), NOW), **kw)


class BuildersTest(SimpleTestCase):
    def test_elasticsearch(self):
        dsl = str(query().to_es_dsl())
        for needle in ("'project_name': 'shop'", "'service.namespace': 'shop'", "'kubernetes.namespace.keyword': 'shop-prod'"):
            self.assertIn(needle, dsl)

    def test_datadog(self):
        q = query().to_datadog_query()
        self.assertIn('project_name:shop', q)
        self.assertIn('@service.namespace:shop', q)

    def test_cloudwatch(self):
        q = query().to_cloudwatch_insights()
        self.assertIn("service.namespace in ['shop']", q)
        self.assertIn("project_name in ['shop']", q)

    def test_splunk(self):
        q = query().to_splunk_spl()
        self.assertIn('kubernetes.namespace IN ("shop-prod")', q)
        self.assertIn('project_name IN ("shop")', q)

    def test_azure_and_gcp(self):
        self.assertIn('tostring(Properties["service.namespace"]) == "shop"', query().to_azure_kql())
        self.assertIn('labels."kubernetes.namespace"="shop-prod"', query().to_gcp_filter())

    def test_without_rules_nothing_changes(self):
        q = LogQuery(project='shop')
        self.assertEqual(q.to_logql_alternatives(), [q.to_logql()])
        self.assertIn('project_name', q.to_splunk_spl())

    def test_loki_one_selector_per_way(self):
        self.assertEqual([q.split('}')[0] + '}' for q in query().to_logql_alternatives()],
                         ['{project_name="shop"}', '{service_namespace="shop"}', '{kubernetes_namespace="shop-prod"}'])

    def test_loki_values_are_escaped(self):
        q = LogQuery(project='sh"op').to_logql()
        self.assertIn('project_name="sh\\"op"', q)


class LokiAdapterTest(SimpleTestCase):
    def entry(self, msg, minutes):
        return LogEntry(timestamp=NOW - timedelta(minutes=minutes), message=msg, service='frontend')

    def test_results_of_every_selector_are_merged_once_newest_first(self):
        provider = LokiLogProvider({'host': 'http://loki:3100'})
        a, b, c = self.entry('a', 3), self.entry('b', 1), self.entry('c', 2)
        with mock.patch.object(provider, '_query_range', side_effect=[[a, b], [b, c], []]) as run:
            got = provider.search('', query())
        self.assertEqual(run.call_count, 3)
        self.assertEqual([e.message for e in got], ['b', 'c', 'a'])

    def test_discovery_finds_a_project_tagged_only_by_a_rule(self):
        provider = LokiLogProvider({'host': 'http://loki:3100'})
        project = mock.Mock(log_rules_clean=lambda: [('service.namespace', 'shop')])
        project.name = 'shop'
        values = {'project_name': [], 'service_namespace': ['shop', 'billing'], 'service_name': ['frontend']}
        with mock.patch.object(provider, '_label_values', side_effect=lambda label, sel=None: values.get(label, [])):
            self.assertEqual(provider.get_indices(project), ['frontend'])
