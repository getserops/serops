"""
Generic Adapter for OpenAI-compatible APIs.
Supports: OpenAI, DeepSeek, Mistral, Ollama, etc.
"""

import openai
import logging
from ..exceptions import ModelDeprecated
from .base import BaseProviderAdapter, AIServiceError

logger = logging.getLogger(__name__)

# Default model — verified against platform.openai.com 2026-08-30.
# ``gpt-3.5-turbo`` and ``gpt-4`` both shut down 2026-10-23 — any
# adapter still defaulting to them will 404 after that date.
DEFAULT_MODEL = 'gpt-5.6-terra'

# Provider IDs shut down by OpenAI 2026-10-23. We fail fast rather
# than burning a request when we can already see the config will
# produce a 404. This only applies when the provider is the OpenAI
# API itself — DeepSeek/Ollama route through the same adapter but
# ship their own model catalog.
_OPENAI_SHUTDOWN_MODELS = {'gpt-3.5-turbo', 'gpt-4'}


class GenericOpenAIAdapter(BaseProviderAdapter):
    def generate(self, prompt: str, config: dict, api_key: str = None,
                 system_prefix: str = None) -> tuple:
        """
        Generate text using OpenAI-compatible API.

        When ``system_prefix`` is supplied, it becomes the first message
        with ``role=system``. OpenAI (since Oct 2024) and DeepSeek both
        auto-cache stable prefixes ≥1024 tokens with no additional API
        flags — sending a system message with our static prompt is all
        it takes. Cache hits are billed at 50% (OpenAI) / 10% (DeepSeek)
        of base input token cost. Ollama serves locally and ignores the
        split.

        Returns:
            tuple: (response_text, error, tokens_input, tokens_output)
                  Returns (None, error, 0, 0) on failure

        Raises:
            ModelDeprecated: If the caller has an OpenAI ``gpt-4`` /
                ``gpt-3.5-turbo`` still configured (both shut down
                2026-10-23). We fail out of band rather than returning
                a generic AIServiceError so the onboarding wizard's
                Test-connection step can render a targeted "update
                your default model" hint.
        """
        # Config extraction
        base_url = config.get('api_base_url')
        model_name = config.get('default_model', DEFAULT_MODEL)
        provider_name = (config.get('name') or '').lower()

        # Fail eagerly for OpenAI shutdown models — outside the try
        # block so the exception propagates rather than being
        # collapsed into a generic AIServiceError. Only enforced
        # against the OpenAI provider itself; DeepSeek / Ollama also
        # route through this adapter but ship their own model catalog.
        if provider_name == 'openai' and model_name in _OPENAI_SHUTDOWN_MODELS:
            raise ModelDeprecated(
                f"OpenAI model '{model_name}' shuts down 2026-10-23. "
                f"Update the provider's default model (recommended: {DEFAULT_MODEL})."
            )

        # Build messages — prepend system role when caller supplied a
        # stable prefix. Order matters: OpenAI/DeepSeek auto-caching
        # keys on the exact byte-prefix of the messages array, so the
        # system message must always come first with identical content
        # across calls.
        messages = []
        if system_prefix:
            messages.append({"role": "system", "content": system_prefix})
        messages.append({"role": "user", "content": prompt})

        try:
            # OpenAI Client — timeout is per-request and defaults to
            # 600s in the SDK. That's too long for a celery worker
            # to hang on a wedged provider (blocks the whole batch
            # pipeline). Clamp to a sane 120s default, override via
            # config.timeout_seconds for slow local Ollama boxes.
            client = openai.OpenAI(
                api_key=api_key or "dummy", # Ollama might not need key
                base_url=base_url,
                timeout=config.get('timeout_seconds', 120),
            )

            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=config.get('temperature', 0.7),
                max_tokens=config.get('max_tokens', 4096)
            )

            content = response.choices[0].message.content

            # Extract token usage
            tokens_input = 0
            tokens_output = 0
            if hasattr(response, 'usage') and response.usage:
                tokens_input = getattr(response.usage, 'prompt_tokens', 0)
                tokens_output = getattr(response.usage, 'completion_tokens', 0)
                logger.debug(f"OpenAI-compatible API token usage: {tokens_input} input, {tokens_output} output")

            # Check for truncation via finish_reason
            finish_reason = response.choices[0].finish_reason
            if finish_reason == 'length':
                partial_text = content or ''
                logger.warning(
                    f"OpenAI-compatible response truncated (finish_reason='length') "
                    f"for model {model_name}. Tokens: {tokens_input} in, {tokens_output} out"
                )
                return None, AIServiceError(
                    'truncated', 'TRUNCATED',
                    'AI response was truncated (hit output token limit).',
                    'Try re-analyzing with a model that supports longer outputs.',
                    raw_error=partial_text[:2000],
                    partial_text=partial_text,
                ), tokens_input, tokens_output

            return content, None, tokens_input, tokens_output

        except Exception as e:
            logger.error(f"OpenAI Adapter Error ({config.get('name')}): {e}")
            return None, self.normalize_error(e), 0, 0

    def normalize_error(self, e: Exception) -> AIServiceError:
        msg = str(e).lower()
        # Timeout — SDK raises openai.APITimeoutError; string check
        # also catches wrapped httpx/urllib3 timeouts from Ollama.
        if 'timeout' in msg or 'timed out' in msg:
            return AIServiceError.from_type('timeout', raw_error=str(e)[:500])
        # Rate limit / quota
        if '429' in msg or 'quota' in msg or 'rate limit' in msg:
            return AIServiceError.from_type('quota_exceeded', raw_error=str(e)[:500])
        # Auth
        if '401' in msg or 'auth' in msg or 'invalid api key' in msg:
            return AIServiceError.from_type('auth_error', raw_error=str(e)[:500])
        # Overloaded (some OpenAI-compat backends surface 529)
        if '529' in msg or 'overloaded' in msg:
            return AIServiceError.from_type('overloaded', raw_error=str(e)[:500])
        # 5xx server errors → distinct from unknown so retry logic can
        # act on it (server_error should back off + retry, unknown
        # generally shouldn't).
        if any(code in msg for code in ('500', '502', '503', '504')) or 'internal server error' in msg:
            return AIServiceError.from_type('server_error', raw_error=str(e)[:500])
        # Network — connection refused / DNS. Common with self-hosted
        # Ollama when the container is down.
        if 'connection' in msg or 'network' in msg or 'name or service not known' in msg:
            return AIServiceError.from_type('network_error', raw_error=str(e)[:500])
        return AIServiceError('unknown', 'UNKNOWN_ERROR', f'Provider error: {str(e)[:100]}', raw_error=str(e)[:500])
