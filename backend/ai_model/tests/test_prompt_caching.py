"""Tests for Commit 2 of the audit follow-up.

Three concerns, one test module:

1. **Prompt splitting** — ``get_batch_analysis_prompt_parts`` returns
   ``(system_static, user_dynamic)`` and the static half is stable
   across batches. If it isn't stable, provider prompt-caching stops
   working and we silently pay full price.

2. **Adapter caching wiring** — Claude adapter passes system_prefix
   into ``cache_control={"type":"ephemeral"}`` on the ``system``
   parameter. OpenAI-compat adapter prepends a ``role=system``
   message. Both are verified against mocked SDK clients so we
   don't need live API calls.

3. **Signature normalisation** — ``_normalize_for_signature`` collapses
   volatile fragments (ports, UUIDs, timestamps, IPs, numeric
   literals, quoted strings) so semantically-identical logs share
   a signature slot.
"""

from unittest.mock import patch, MagicMock

from django.test import SimpleTestCase

# ClaudeAdapter is imported inside individual test methods rather
# than at module level. Reason: test_adapters.py's ClaudeAdapterTest
# patches sys.modules['anthropic'] in setUpClass and pops
# ai_model.adapters.claude from sys.modules in tearDownClass. A
# module-level import here would capture a reference to the
# pre-teardown ClaudeAdapter class, and @patch on the freshly-reimported
# module wouldn't affect that stale reference — creating an
# order-dependent test failure where these pass in isolation but
# fail after test_adapters.py ran. GenericOpenAIAdapter has no
# such coupling (test_adapters doesn't touch sys.modules['openai'])
# so it's fine at module scope.
from ai_model.adapters.openai_generic import GenericOpenAIAdapter
from ai_model.prompt_context import DataSourceContext
from ai_model.prompts import (
    get_batch_analysis_prompt,
    get_batch_analysis_prompt_parts,
    get_batch_analysis_system_prompt,
)
from ai_model.tasks import _normalize_for_signature


# ---------------------------------------------------------------------------
# Prompt splitting
# ---------------------------------------------------------------------------


class PromptSplittingTest(SimpleTestCase):
    """The system prefix must be byte-stable across batches — otherwise
    prompt caching never hits."""

    def _sample_parts(self, batch_id='batch-a'):
        batch_data = {
            'batch_id': batch_id,
            'timestamp': '2026-09-01T12:00:00Z',
            'environment': 'production',
        }
        return get_batch_analysis_prompt_parts(
            DataSourceContext(
                batch_data=batch_data,
                logs=['[00:00:00] [ERROR] [svc] boom'],
            ),
        )

    def test_returns_tuple_of_two_strings(self):
        system, user = self._sample_parts()
        self.assertIsInstance(system, str)
        self.assertIsInstance(user, str)
        self.assertGreater(len(system), 0)
        self.assertGreater(len(user), 0)

    def test_system_prefix_is_stable_across_calls(self):
        """Change nothing but the batch_id — system prefix must be
        byte-identical or caching stops working."""
        s1, _ = self._sample_parts(batch_id='batch-a')
        s2, _ = self._sample_parts(batch_id='batch-b')
        self.assertEqual(s1, s2,
                         "System prefix leaked dynamic content — caching will not hit.")

    def test_system_prefix_meets_min_cache_size(self):
        """Claude Sonnet 5 minimum cacheable prefix is 1024 tokens
        (~4096 chars). If we drop below this, prompt caching becomes
        a no-op with no error, hiding the regression. Assert well
        clear of the boundary."""
        system, _ = self._sample_parts()
        self.assertGreater(
            len(system), 4096,
            f"System prefix is only {len(system)} chars — below Claude "
            f"Sonnet 5 cache-write minimum (~4096 chars = 1024 tokens). "
            f"Something got removed from _BATCH_ANALYSIS_SYSTEM.",
        )

    def test_system_prefix_has_no_interpolation_placeholders(self):
        """A stray ``{something}`` in _BATCH_ANALYSIS_SYSTEM would kill
        caching because Python f-string evaluation would inject
        per-call values. Regression guard."""
        system = get_batch_analysis_system_prompt()
        # Legitimate JSON template braces contain quoted keys —
        # anything looking like an interpolation slot is suspect.
        # Simple heuristic: {} with no quote inside is a smell.
        import re
        # Find all {…} that aren't part of the JSON schema (which has
        # keys like {"summary": ...} — always quoted immediately).
        for match in re.finditer(r'\{([^{}]*)\}', system):
            content = match.group(1).strip()
            # JSON schema braces contain quoted keys / brackets
            if content and not content.startswith('"') and not content.startswith('\n'):
                # Real interpolation slot like {batch_id} — reject
                self.assertFalse(
                    re.match(r'^[a-z_][a-z0-9_]*$', content),
                    f"System prefix contains suspected f-string slot: "
                    f"{{{content}}}. This would kill provider caching.",
                )

    def test_user_content_changes_per_batch(self):
        """Sanity: dynamic half really does vary."""
        _, u1 = self._sample_parts(batch_id='batch-a')
        _, u2 = self._sample_parts(batch_id='batch-b')
        self.assertNotEqual(u1, u2)
        self.assertIn('batch-a', u1)
        self.assertIn('batch-b', u2)

    def test_concatenation_wrapper_produces_equivalent_output(self):
        """Backward-compat: ``get_batch_analysis_prompt`` (single-string
        variant) must return system + user concatenated, so chat/manual
        paths that never adopted the split still get the same prompt
        content."""
        system, user = self._sample_parts()
        batch_data = {
            'batch_id': 'batch-a', 'timestamp': '2026-09-01T12:00:00Z',
            'environment': 'production',
        }
        combined = get_batch_analysis_prompt(
            DataSourceContext(
                batch_data=batch_data,
                logs=['[00:00:00] [ERROR] [svc] boom'],
            ),
        )
        # The concatenation form should contain both halves and no
        # significant new content. Whitespace between the two blocks
        # is expected.
        self.assertIn(system, combined)
        self.assertIn(user, combined)


# ---------------------------------------------------------------------------
# Adapter caching wiring
# ---------------------------------------------------------------------------


class ClaudeCacheControlTest(SimpleTestCase):
    """Verify Claude adapter attaches cache_control when system_prefix is set."""

    @patch('ai_model.adapters.claude.anthropic')
    def test_system_prefix_sets_cache_control(self, mock_anthropic):
        # See module docstring — import inside test to avoid
        # order-dependency with test_adapters.py's sys.modules
        # manipulation.
        from ai_model.adapters.claude import ClaudeAdapter

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.stop_reason = 'end_turn'
        mock_message.content = [MagicMock(text='ok')]
        mock_message.usage.input_tokens = 100
        mock_message.usage.output_tokens = 5
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        adapter = ClaudeAdapter()
        # Prefix long enough to be cache-worthy (well over 4096 chars)
        long_prefix = 'x' * 5000
        adapter.generate(
            prompt='dynamic content',
            config={'default_model': 'claude-sonnet-5'},
            api_key='sk-test',
            system_prefix=long_prefix,
        )

        kwargs = mock_client.messages.create.call_args.kwargs
        self.assertIn('system', kwargs, "Claude adapter must pass system=[…] when system_prefix supplied")
        system_blocks = kwargs['system']
        self.assertIsInstance(system_blocks, list, "system must be a list of blocks (not raw string) to attach cache_control")
        self.assertEqual(system_blocks[0]['type'], 'text')
        self.assertEqual(system_blocks[0]['text'], long_prefix)
        self.assertEqual(
            system_blocks[0]['cache_control'], {'type': 'ephemeral'},
            "cache_control must be ephemeral — the whole point of the refactor.",
        )

    @patch('ai_model.adapters.claude.anthropic')
    def test_no_system_prefix_no_system_block(self, mock_anthropic):
        """Backward compat: chat / manual paths that pass no
        system_prefix should get the pre-refactor behaviour — just
        messages, no system= kwarg (which would be noise on the wire)."""
        from ai_model.adapters.claude import ClaudeAdapter

        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.stop_reason = 'end_turn'
        mock_message.content = [MagicMock(text='ok')]
        mock_message.usage.input_tokens = 10
        mock_message.usage.output_tokens = 5
        mock_client.messages.create.return_value = mock_message
        mock_anthropic.Anthropic.return_value = mock_client

        ClaudeAdapter().generate(
            prompt='hi', config={'default_model': 'claude-sonnet-5'}, api_key='sk-test',
        )

        kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn('system', kwargs)


class OpenAISystemMessageTest(SimpleTestCase):
    """Verify OpenAI-compat adapter prepends role=system when
    system_prefix is set (OpenAI + DeepSeek auto-cache on stable
    system messages ≥1024 tokens)."""

    def _build_mock_response(self):
        mock = MagicMock()
        mock.choices = [MagicMock()]
        mock.choices[0].message.content = 'ok'
        mock.choices[0].finish_reason = 'stop'
        mock.usage.prompt_tokens = 100
        mock.usage.completion_tokens = 5
        return mock

    @patch('ai_model.adapters.openai_generic.openai')
    def test_system_prefix_prepends_system_message(self, mock_openai):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._build_mock_response()
        mock_openai.OpenAI.return_value = mock_client

        GenericOpenAIAdapter().generate(
            prompt='dynamic content',
            config={'name': 'deepseek', 'default_model': 'deepseek-v4-flash'},
            api_key='sk-test',
            system_prefix='static schema and rules',
        )

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = kwargs['messages']
        # Order matters — auto-caching keys on exact prefix bytes.
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]['role'], 'system')
        self.assertEqual(messages[0]['content'], 'static schema and rules')
        self.assertEqual(messages[1]['role'], 'user')
        self.assertEqual(messages[1]['content'], 'dynamic content')

    @patch('ai_model.adapters.openai_generic.openai')
    def test_no_system_prefix_no_system_message(self, mock_openai):
        """Backward compat: chat paths get a single user message."""
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._build_mock_response()
        mock_openai.OpenAI.return_value = mock_client

        GenericOpenAIAdapter().generate(
            prompt='hi',
            config={'name': 'openai', 'default_model': 'gpt-5.6-terra'},
            api_key='sk-test',
        )

        kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = kwargs['messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['role'], 'user')


# ---------------------------------------------------------------------------
# Signature normalisation
# ---------------------------------------------------------------------------


class SignatureNormalizationTest(SimpleTestCase):
    """Semantically identical log lines must collapse to one signature."""

    def test_port_variants_collapse(self):
        """The original bug: redis:6379 vs redis:6380 = different sigs."""
        a = _normalize_for_signature('Connection refused to redis:6379')
        b = _normalize_for_signature('Connection refused to redis:6380')
        self.assertEqual(a, b)

    def test_ip_variants_collapse(self):
        a = _normalize_for_signature('Timeout waiting for 10.0.0.5')
        b = _normalize_for_signature('Timeout waiting for 10.0.0.6')
        self.assertEqual(a, b)

    def test_uuid_variants_collapse(self):
        a = _normalize_for_signature('Request 550e8400-e29b-41d4-a716-446655440000 failed')
        b = _normalize_for_signature('Request 6ba7b810-9dad-11d1-80b4-00c04fd430c8 failed')
        self.assertEqual(a, b)

    def test_hex_hash_variants_collapse(self):
        a = _normalize_for_signature('Cache miss for key deadbeefcafebabe')
        b = _normalize_for_signature('Cache miss for key feedfacef00dbadc')
        self.assertEqual(a, b)

    def test_iso_timestamp_variants_collapse(self):
        a = _normalize_for_signature('Job started at 2026-09-01T12:00:00Z')
        b = _normalize_for_signature('Job started at 2026-09-01T13:00:00Z')
        self.assertEqual(a, b)

    def test_quoted_string_variants_collapse(self):
        a = _normalize_for_signature('User "alice" denied')
        b = _normalize_for_signature('User "bob" denied')
        self.assertEqual(a, b)

    def test_numeric_variants_collapse(self):
        a = _normalize_for_signature('Latency 250ms exceeds budget')
        b = _normalize_for_signature('Latency 400ms exceeds budget')
        self.assertEqual(a, b)

    def test_different_error_messages_do_not_collapse(self):
        """Regression guard: over-normalisation would kill signal.
        Genuinely different errors must stay distinct."""
        a = _normalize_for_signature('Connection refused to redis')
        b = _normalize_for_signature('Timeout reading from postgres')
        self.assertNotEqual(a, b)

    def test_empty_message_safe(self):
        self.assertEqual(_normalize_for_signature(''), '')
        self.assertEqual(_normalize_for_signature(None), '')

    def test_message_with_no_volatile_parts_preserved(self):
        """A message with nothing to normalise passes through."""
        msg = 'OutOfMemoryError: Java heap space'
        # 'Java' unchanged, no numbers, no quotes — should be
        # bit-identical (aside from any incidental substitutions).
        normalized = _normalize_for_signature(msg)
        self.assertEqual(normalized, msg)
