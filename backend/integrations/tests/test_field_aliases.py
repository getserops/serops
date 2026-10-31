"""Tests for the canonical field-alias resolution.

The alias module (`integrations/field_aliases.py`) is the single source
of truth for accepted alternatives to SerOps' canonical field names.
These tests lock in three things:

1. Alias lists are non-empty and put the canonical name FIRST (so it
   wins when both canonical and alias are present in a doc).
2. `first_present` returns the first non-empty value in alias order
   (canonical > alias1 > alias2 > ...) and falls back to the default.
3. `LogQuery.to_es_dsl` / `to_datadog_query` / `to_cloudwatch_insights`
   emit alias-aware clauses so users with Datadog USM (`service`, `env`),
   OpenTelemetry (`service.name`, `deployment.environment`), or K8s
   (`app`) tagging get results without retagging at source.

Loki (`to_logql`) is deliberately NOT alias-aware — Loki stream
selectors AND across labels and can't easily OR the same value across
DIFFERENT label names. Loki users must tag with SerOps' canonical
names. See `docs/how-to/configure-data-collection.md` for guidance.
"""

from datetime import datetime

from django.test import SimpleTestCase

from integrations.field_aliases import (
    ENVIRONMENT_ALIASES,
    LOG_LEVEL_ALIASES,
    ORGANISATION_NAME_ALIASES,
    PROJECT_NAME_ALIASES,
    SERVICE_NAME_ALIASES,
    first_present,
)
from integrations.schemas import LogQuery


class AliasListsTest(SimpleTestCase):
    """Alias lists: non-empty, canonical first, no duplicates."""

    def test_service_name_canonical_is_first(self):
        self.assertEqual(SERVICE_NAME_ALIASES[0], 'service_name')
        self.assertGreater(len(SERVICE_NAME_ALIASES), 1)

    def test_environment_canonical_is_first(self):
        self.assertEqual(ENVIRONMENT_ALIASES[0], 'environment')
        self.assertGreater(len(ENVIRONMENT_ALIASES), 1)

    def test_log_level_canonical_is_first(self):
        self.assertEqual(LOG_LEVEL_ALIASES[0], 'log_level')

    def test_project_name_canonical_is_first(self):
        self.assertEqual(PROJECT_NAME_ALIASES[0], 'project_name')

    def test_organisation_name_canonical_is_first(self):
        self.assertEqual(ORGANISATION_NAME_ALIASES[0], 'organisation_name')

    def test_no_duplicates_within_list(self):
        for name, aliases in [
            ('service', SERVICE_NAME_ALIASES),
            ('env', ENVIRONMENT_ALIASES),
            ('level', LOG_LEVEL_ALIASES),
            ('project', PROJECT_NAME_ALIASES),
            ('org', ORGANISATION_NAME_ALIASES),
        ]:
            self.assertEqual(
                len(aliases), len(set(aliases)),
                f"{name} alias list contains duplicates: {aliases}",
            )


class FirstPresentTest(SimpleTestCase):
    """`first_present` returns the first non-empty alias in order."""

    def test_returns_canonical_when_present(self):
        doc = {'service_name': 'checkout', 'service': 'wrong'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'checkout')

    def test_falls_back_to_alias_when_canonical_missing(self):
        doc = {'service': 'checkout'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'checkout')

    def test_skips_empty_canonical(self):
        # A present-but-empty canonical must not shadow a real alias.
        doc = {'service_name': '', 'app': 'api'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'api')

    def test_skips_none_canonical(self):
        doc = {'service_name': None, 'service': 'api'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'api')

    def test_default_when_no_alias_present(self):
        self.assertEqual(
            first_present({}, SERVICE_NAME_ALIASES, default='unknown'),
            'unknown',
        )

    def test_empty_string_default(self):
        self.assertEqual(first_present({}, SERVICE_NAME_ALIASES), '')

    def test_otel_dotted_alias(self):
        doc = {'service.name': 'api'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'api')

    def test_k8s_standard_alias(self):
        doc = {'app.kubernetes.io/name': 'checkout'}
        self.assertEqual(first_present(doc, SERVICE_NAME_ALIASES), 'checkout')


class LogQueryEsDslAliasesTest(SimpleTestCase):
    """to_es_dsl emits bool.should over aliases for canonical fields."""

    def _filters(self, **kwargs):
        return LogQuery(**kwargs).to_es_dsl()['query']['bool']['filter']

    def test_project_uses_bool_should_over_aliases(self):
        """Every alias must appear in BOTH forms.

        The assertion used to be ``== set(PROJECT_NAME_ALIASES)``, which broke
        when the E9-1 fix started emitting a ``.keyword`` variant beside each
        alias — on a dynamically-mapped index the plain field is analysed, so
        a term query against it never matches, while ILM templates with an
        explicit keyword mapping only have the plain field. Matching both is
        the point. The test asserted a 1:1 mapping that was never the
        contract, so it failed on correct output.
        """
        filters = self._filters(project='demo')
        clause = filters[0]
        self.assertIn('bool', clause)
        emitted = {list(s['term'].keys())[0] for s in clause['bool']['should']}
        for alias in PROJECT_NAME_ALIASES:
            with self.subTest(alias=alias):
                self.assertIn(alias, emitted)
                self.assertIn(f'{alias}.keyword', emitted)

    def test_project_emits_no_unexpected_fields(self):
        """Complements the above: nothing beyond the aliases and their
        .keyword variants should be queried."""
        clause = self._filters(project='demo')[0]
        emitted = {list(s['term'].keys())[0] for s in clause['bool']['should']}
        allowed = set(PROJECT_NAME_ALIASES) | {
            f'{a}.keyword' for a in PROJECT_NAME_ALIASES
        }
        self.assertEqual(emitted, allowed)

    def test_keyword_variant_is_not_double_suffixed(self):
        """An alias already ending in .keyword must not become
        ``x.keyword.keyword``."""
        emitted = {
            list(s['term'].keys())[0]
            for s in self._filters(project='demo')[0]['bool']['should']
        }
        self.assertFalse([f for f in emitted if f.endswith('.keyword.keyword')])

    def test_environment_includes_datadog_usm_env_alias(self):
        filters = self._filters(environment='prod')
        env_clause = next(f for f in filters if 'bool' in f)
        aliases = {list(s['terms'].keys())[0] for s in env_clause['bool']['should']}
        self.assertIn('env', aliases)  # Datadog USM
        self.assertIn('service.environment', aliases)  # ECS
        # every spelling of the environment, not just the one asked for
        values = env_clause['bool']['should'][0]['terms']['environment']
        self.assertEqual(values, ['prod', 'production', 'prd'])

    def test_services_includes_otel_and_k8s_aliases(self):
        filters = self._filters(services=['checkout'])
        svc_clause = next(f for f in filters if 'bool' in f)
        aliases = {list(s['terms'].keys())[0] for s in svc_clause['bool']['should']}
        self.assertIn('service.name', aliases)   # OTEL
        self.assertIn('app', aliases)            # K8s

    def test_severity_matches_every_spelling_on_every_level_field(self):
        filters = self._filters(severity=['ERROR', 'WARNING'])
        sev_clause = next(f for f in filters if 'bool' in f)
        levels, words = sev_clause['bool']['should']
        qs = levels['query_string']
        for field in ('log_level.keyword', 'level', 'log.level', 'severity_text'):
            self.assertIn(field, qs['fields'])
        for spelling in ('"WARN"', '"warn"', '"Warning"', '"ERROR"', '"error"', '50', '40'):
            self.assertIn(spelling, qs['query'].split(' OR '))
        self.assertTrue(qs['lenient'])  # a numeric level field must not fail the search
        # unstructured logs: no level field, reached through the message
        self.assertEqual(words['query_string']['fields'], ['message'])
        self.assertIn('exception', words['query_string']['query'])

    def test_minimum_should_match_is_1(self):
        # Any single alias hit is enough — never require ALL.
        filters = self._filters(project='demo')
        self.assertEqual(filters[0]['bool']['minimum_should_match'], 1)


class LogQueryDatadogAliasesTest(SimpleTestCase):
    """to_datadog_query emits OR expressions across aliases."""

    def test_service_includes_usm_service_alias(self):
        dd = LogQuery(services=['checkout']).to_datadog_query()
        # Canonical AND USM alias both present in the OR expression
        self.assertIn('@service_name:checkout', dd)
        self.assertIn(' service:checkout', dd)   # USM reserved attribute / tag
        self.assertIn('app.kubernetes.io\\/name:checkout', dd)  # '/' escaped

    def test_environment_includes_env_alias(self):
        dd = LogQuery(environment='prod').to_datadog_query()
        # tags (what DD_TAGS / the agent's tags: produce) and attributes
        self.assertIn(' env:(prod OR production OR prd)', dd)
        self.assertIn('@env:(prod OR production OR prd)', dd)
        self.assertIn('(environment:(prod OR production OR prd)', dd)

    def test_severity_uses_status_and_aliases(self):
        dd = LogQuery(severity=['error']).to_datadog_query()
        # `status:` (Datadog native, no @) plus @log_level etc.
        self.assertIn('status:(error OR err OR alert OR emerg OR emergency)', dd)
        self.assertIn('@level:(ERROR OR error OR Error', dd)
        self.assertIn('exception', dd)  # unstructured logs default to status info


class LogQueryCloudWatchAliasesTest(SimpleTestCase):
    """to_cloudwatch_insights emits `or` across aliases."""

    def test_service_includes_aliases(self):
        cw = LogQuery(services=['checkout']).to_cloudwatch_insights()
        self.assertIn("service_name in ['checkout']", cw)
        self.assertIn("service in ['checkout']", cw)  # Datadog USM
        self.assertIn(" or ", cw)

    def test_environment_includes_env_alias(self):
        cw = LogQuery(environment='prod').to_cloudwatch_insights()
        self.assertIn("environment in ['prod', 'production', 'prd']", cw)
        self.assertIn("env in ['prod', 'production', 'prd']", cw)


class LogQueryLokiUnchangedTest(SimpleTestCase):
    """to_logql is deliberately canonical-only (Loki can't OR across labels)."""

    def test_canonical_only(self):
        logql = LogQuery(services=['checkout']).to_logql()
        # Canonical service_name is used
        self.assertIn('service_name=~', logql)
        # Aliases are NOT emitted (would break Loki stream selector semantics)
        self.assertNotIn('service=~', logql)
        self.assertNotIn('app=~', logql)
