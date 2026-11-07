"""The startup check that tells operators env-var AI keys do nothing.

SerOps reads provider keys from OrganisationAPIKey, never the environment — the
env fallback was removed in org_settings migration 0011. The documentation did
not keep up, and the misconception reappeared in five places: .env.example, the
quick-start README, the backend README, the Helm chart's production values
example, and the env_key_name help text.

Prose only reaches whoever reads that file. The person who needs telling has
already set the variable and is watching a deployment do nothing, so the
application says it at startup instead.
"""
from unittest import mock

from django.test import SimpleTestCase

from ai_model.checks import (
    UNUSED_PROVIDER_ENV_VARS,
    ai_provider_env_keys_unused,
)

ALL_VARS = UNUSED_PROVIDER_ENV_VARS


def _run(**env):
    """Run the check with a clean environment plus `env`."""
    base = {name: '' for name in ALL_VARS}
    base.update(env)
    with mock.patch.dict('os.environ', base, clear=False):
        return ai_provider_env_keys_unused(app_configs=None)


class SilentWhenCorrectlyConfiguredTest(SimpleTestCase):
    """The check has to be quiet in the normal case or it becomes noise that
    operators learn to scroll past — which would defeat the point."""

    def test_nothing_set_produces_nothing(self):
        self.assertEqual(_run(), [])

    def test_unrelated_variables_are_ignored(self):
        self.assertEqual(_run(DJANGO_SECRET_KEY='x', REDIS_URL='y'), [])

    def test_empty_string_is_not_treated_as_set(self):
        """A chart that templates an unset secret to "" must not trip it."""
        self.assertEqual(_run(ANTHROPIC_API_KEY=''), [])


class WarnsAboutKeysNothingReadsTest(SimpleTestCase):
    def test_each_unused_variable_warns(self):
        for name in UNUSED_PROVIDER_ENV_VARS:
            with self.subTest(var=name):
                found = _run(**{name: 'secret-value'})
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0].id, 'ai.W001')

    def test_the_message_names_the_variable_the_operator_set(self):
        found = _run(ANTHROPIC_API_KEY='sk-ant-xxx')
        self.assertIn('ANTHROPIC_API_KEY', found[0].msg)

    def test_the_hint_says_where_keys_actually_go(self):
        found = _run(GOOGLE_API_KEY='g')
        self.assertIn('Settings', found[0].hint)
        self.assertIn('AI Providers', found[0].hint)

    def test_the_secret_value_is_never_echoed(self):
        """The whole point is that this appears in deployment logs."""
        secret = 'sk-ant-do-not-log-me'
        found = _run(ANTHROPIC_API_KEY=secret)
        self.assertNotIn(secret, found[0].msg)
        self.assertNotIn(secret, found[0].hint)

    def test_several_set_produce_one_warning_each(self):
        found = _run(ANTHROPIC_API_KEY='a', GOOGLE_API_KEY='b',
                     DEEPSEEK_API_KEY='c')
        self.assertEqual(len(found), 3)
        self.assertEqual({f.id for f in found}, {'ai.W001'})


class OpenAIKeyIsNoLongerReadTest(SimpleTestCase):
    """OPENAI_API_KEY used to feed issue-similarity embeddings. Embeddings now
    use the organisation's own provider (external review, v1.2.13), so the
    variable does nothing and gets the same warning as its siblings."""

    def test_openai_key_in_the_environment_warns_like_the_others(self):
        found = _run(OPENAI_API_KEY='sk-openai')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].id, 'ai.W001')
        self.assertIn('OPENAI_API_KEY', found[0].msg)

    def test_openai_key_value_is_never_echoed(self):
        secret = 'sk-openai-secret'
        found = _run(OPENAI_API_KEY=secret)
        self.assertNotIn(secret, found[0].msg)
        self.assertNotIn(secret, found[0].hint)


class CheckIsRegisteredTest(SimpleTestCase):
    """Registration happens in AiModelConfig.ready(); an unregistered check is
    a file nobody runs."""

    def test_registered_under_the_ai_tag(self):
        from django.core.checks.registry import registry
        self.assertIn(ai_provider_env_keys_unused, registry.get_checks())
        self.assertIn('ai', registry.tags_available())
