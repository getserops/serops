"""Adapter for Google Gemini via the google-genai SDK.

Migrated 2026-08-30 from the deprecated ``google-generativeai`` package
(EOL Aug 2025) to ``google-genai`` — Google's unified GenAI client that
covers both Vertex and Gemini API endpoints. Public surface preserved
so nothing else in ai_service.py had to change.

Reference: https://ai.google.dev/gemini-api/docs/migrate
"""

import logging

from google import genai
from google.genai import types

from .base import BaseProviderAdapter, AIServiceError

logger = logging.getLogger(__name__)

# Default model — verified against ai.google.dev 2026-08-30.
# Kept as a module constant so tests can patch/inspect it and the
# adapter never falls back to a shut-down ID silently.
DEFAULT_MODEL = 'gemini-3.5-flash'


class GeminiAdapter(BaseProviderAdapter):
    def generate(self, prompt: str, config: dict, api_key: str = None,
                 system_prefix: str = None) -> tuple:
        """Generate text via the Gemini API.

        When ``system_prefix`` is supplied, it's passed as the
        ``system_instruction`` — the SDK's native slot for a stable
        prefix. Gemini 2.5+ has implicit caching auto-enabled BUT the
        minimum cacheable prefix on 3.5-flash is 4096 tokens; the
        SerOps analysis system prompt is ~2500 tokens, so we don't
        expect a cache hit today. Kept the wiring in place so a later
        prefix growth (or an explicit-cache switch) automatically
        starts benefiting without code changes.

        Returns (response_text, error, tokens_input, tokens_output).
        On failure returns (None, error, 0, 0) — tokens are reported when
        the request actually reached the API and produced usage metadata
        (e.g. truncated responses still count).
        """
        try:
            if not api_key:
                return None, AIServiceError('auth_error', 'AUTH_MISSING', 'No API Key provided'), 0, 0

            # Explicit request timeout via http_options — the Gemini
            # SDK has no request-level default which meant a wedged
            # call could hang the celery worker until Kubernetes
            # killed the pod. Bounded to 120s by default.
            timeout_ms = int(config.get('timeout_seconds', 120)) * 1000
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=timeout_ms),
            )
            model_name = config.get('default_model', DEFAULT_MODEL)

            # Route system_prefix through the SDK's system_instruction
            # slot rather than concatenating into contents — the SDK
            # gives it slightly better implicit-cache treatment and
            # keeps the wire payload cleaner.
            config_kwargs = {'max_output_tokens': config.get('max_output_tokens', 8192)}
            if system_prefix:
                config_kwargs['system_instruction'] = system_prefix
            generation_config = types.GenerateContentConfig(**config_kwargs)

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=generation_config,
            )

            tokens_input = 0
            tokens_output = 0
            usage = getattr(response, 'usage_metadata', None)
            if usage is not None:
                tokens_input = getattr(usage, 'prompt_token_count', 0) or 0
                tokens_output = getattr(usage, 'candidates_token_count', 0) or 0
                logger.debug(f"Gemini token usage: {tokens_input} input, {tokens_output} output")

            # Truncation surfaces as finish_reason=MAX_TOKENS in both the
            # old and new SDK, but the accessor path shifted — candidates[0]
            # is now a Candidate dataclass rather than a proto wrapper.
            candidates = getattr(response, 'candidates', None) or []
            if candidates:
                finish_reason = getattr(candidates[0], 'finish_reason', None)
                finish_reason_name = getattr(finish_reason, 'name', str(finish_reason) if finish_reason else '')
                if finish_reason_name == 'MAX_TOKENS':
                    partial_text = ''
                    try:
                        partial_text = response.text or ''
                    except Exception:
                        partial_text = '[could not extract partial text]'
                    logger.warning(
                        f"Gemini response truncated (MAX_TOKENS) for model {model_name}. "
                        f"Tokens: {tokens_input} in, {tokens_output} out"
                    )
                    return None, AIServiceError(
                        'truncated', 'TRUNCATED',
                        'AI response was truncated (hit output token limit).',
                        'Try re-analyzing with a model that supports longer outputs.',
                        raw_error=partial_text[:2000],
                        partial_text=partial_text,
                    ), tokens_input, tokens_output

            return response.text, None, tokens_input, tokens_output

        except Exception as e:
            logger.error(f"Gemini Adapter Error: {e}")
            return None, self.normalize_error(e), 0, 0

    def normalize_error(self, e: Exception) -> AIServiceError:
        msg = str(e).lower()
        # Timeout — deadlineexceeded is grpc-style, timeout is http-style.
        if 'timeout' in msg or 'timed out' in msg or 'deadline exceeded' in msg:
            return AIServiceError.from_type('timeout', raw_error=str(e)[:500])
        # Rate limit / quota
        if '429' in msg or 'quota' in msg or 'resource_exhausted' in msg or 'rate limit' in msg:
            return AIServiceError.from_type('quota_exceeded', raw_error=str(e)[:500])
        # Auth
        if '401' in msg or 'unauthenticated' in msg or 'permission_denied' in msg or 'invalid api key' in msg:
            return AIServiceError.from_type('auth_error', raw_error=str(e)[:500])
        # Content filter / safety block — Gemini has a strong content
        # filter that returns SAFETY blocks. Users can retry only by
        # rephrasing / redacting; retry logic should NOT loop.
        if 'safety' in msg or 'blocked' in msg or 'prohibited_content' in msg:
            return AIServiceError.from_type('content_blocked', raw_error=str(e)[:500])
        # 5xx server errors
        if any(code in msg for code in ('500', '502', '503', '504')) or 'internal server error' in msg:
            return AIServiceError.from_type('server_error', raw_error=str(e)[:500])
        # Network layer
        if 'connection' in msg or 'network' in msg or 'name or service not known' in msg:
            return AIServiceError.from_type('network_error', raw_error=str(e)[:500])
        # Unbounded str(e) previously — some Gemini exceptions carry
        # the full response JSON, which spammed our logs. Cap it.
        return AIServiceError('unknown', 'UNKNOWN_ERROR', f'Provider error: {str(e)[:100]}', raw_error=str(e)[:500])
