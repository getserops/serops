from django.test import SimpleTestCase

from ai_model.prompts import _BATCH_ANALYSIS_SYSTEM


class OneIssuePerRootCauseTest(SimpleTestCase):
    """One shared cause (cache, DNS, certificate) is one issue, not one per service."""

    def test_rule_asks_for_one_issue_per_root_cause(self):
        self.assertIn('ONE ISSUE PER ROOT CAUSE', _BATCH_ANALYSIS_SYSTEM)
        self.assertNotIn('ONE ISSUE PER COMPONENT', _BATCH_ANALYSIS_SYSTEM)

    def test_schema_has_affected_services(self):
        self.assertIn('"affected_services"', _BATCH_ANALYSIS_SYSTEM)
