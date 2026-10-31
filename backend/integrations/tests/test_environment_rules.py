"""A project rule whose value names the environment puts its logs in that
environment too: ``kubernetes.namespace_name = production`` for Production.
Container Insights logs carry the namespace, never an environment field."""
from django.test import SimpleTestCase

from integrations.schemas import LogQuery

NS = "kubernetes.namespace_name"


def query(value="production", environment="production"):
    return LogQuery(project="shop", environment=environment, project_rules=[(NS, value)])


def env_clause(q):
    """The CloudWatch environment filter, which starts at the environment field."""
    where = q.to_cloudwatch_insights().split(" | sort")[0]
    return where[where.index("((environment in"):]


class EnvironmentRulesTest(SimpleTestCase):
    def test_a_rule_naming_the_environment_says_it(self):
        self.assertEqual(query().environment_rules(), [(NS, "production")])
        self.assertEqual(query("prod").environment_rules(), [(NS, "prod")])

    def test_a_rule_naming_something_else_does_not(self):
        self.assertEqual(query("shop").environment_rules(), [])
        self.assertEqual(query("staging").environment_rules(), [])

    def test_the_environment_labels_count(self):
        q = LogQuery(project="shop", environment="production", environment_labels=["shop-live"],
                     project_rules=[(NS, "shop-live")])
        self.assertEqual(q.environment_rules(), [(NS, "shop-live")])

    def test_cloudwatch(self):
        self.assertIn("(kubernetes.namespace_name in ['production'])", env_clause(query()))
        self.assertNotIn("kubernetes", env_clause(query("shop")))

    def test_elasticsearch(self):
        env = query().to_es_dsl()["query"]["bool"]["filter"]
        self.assertIn("{'term': {'kubernetes.namespace_name': 'production'}}", str(env[-1]))
        self.assertNotIn("namespace", str(query("shop").to_es_dsl()["query"]["bool"]["filter"][-1]))

    def test_loki_rule_query_needs_no_environment_label(self):
        base, rule = query().to_logql_alternatives()
        self.assertIn('environment=~', base)
        self.assertIn('kubernetes_namespace_name="production"', rule)
        self.assertNotIn('environment=~', rule)
        _, other = query("shop").to_logql_alternatives()
        self.assertIn('environment=~', other)

    def test_datadog(self):
        # As a tag and as an attribute: once for the project, once for the environment.
        self.assertEqual(query().to_datadog_query().count("kubernetes.namespace_name:production"), 4)
        self.assertEqual(query("shop").to_datadog_query().count("kubernetes.namespace_name:"), 2)

    def test_splunk(self):
        self.assertEqual(query().to_splunk_spl().count('kubernetes.namespace_name IN ("production")'), 2)

    def test_azure(self):
        self.assertIn('tostring(Properties.environment) in~ ("production", "prod", "prd") or '
                      'tostring(Properties["kubernetes.namespace_name"]) == "production"', query().to_azure_kql())

    def test_gcp(self):
        self.assertIn('OR labels."kubernetes.namespace_name"="production")', query().to_gcp_filter())
