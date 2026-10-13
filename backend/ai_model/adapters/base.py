"""
Base Adapter Interface for AI Providers.
This ensures all providers (OpenAI, Gemini, Claude, etc.) conform to a strict contract.
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any, Optional

class AIServiceError:
    """Wrapper class for AI service errors (Cross-Adapter Standard)"""

    ERROR_TYPES = {
        'quota_exceeded': {
            'code': 'QUOTA_EXCEEDED',
            'message': 'AI service rate limit reached. Will retry automatically.',
            'user_action': 'Wait a few minutes or check your API quota.'
        },
        'auth_error': {
            'code': 'AUTH_ERROR',
            'message': 'API authentication failed.',
            'user_action': 'Check if API key is valid and properly configured.'
        },
        'network_error': {
            'code': 'NETWORK_ERROR',
            'message': 'Connection to AI service failed.',
            'user_action': 'Check network connectivity and retry.'
        },
        'content_blocked': {
            'code': 'CONTENT_BLOCKED',
            'message': 'Content was blocked by safety filters.',
            'user_action': 'Review the logs for sensitive content.'
        },
        'timeout': {
            'code': 'TIMEOUT',
            'message': 'Request timed out.',
            'user_action': 'The batch may be too large. Try with fewer logs.'
        },
        'overloaded': {
            'code': 'OVERLOADED',
            'message': 'Provider is overloaded and rejected the request.',
            'user_action': 'Retry shortly — provider capacity is transiently degraded.'
        },
        'server_error': {
            'code': 'SERVER_ERROR',
            'message': 'Provider returned a 5xx server error.',
            'user_action': 'Provider outage or bug. Check provider status page and retry.'
        },
        'provider_not_supported': {
            'code': 'PROVIDER_NOT_SUPPORTED',
            'message': 'AI provider not yet implemented.',
            'user_action': 'Select a different AI provider.'
        },
        'truncated': {
            'code': 'TRUNCATED',
            'message': 'AI response was truncated (hit output token limit).',
            'user_action': 'Try re-analyzing with a model that supports longer outputs.'
        },
        'unknown': {
            'code': 'UNKNOWN_ERROR',
            'message': 'An unexpected error occurred.',
            'user_action': 'Check logs for details and retry.'
        }
    }

    def __init__(self, error_type: str, code: str, message: str, user_action: str = None,
                 raw_error: str = None, partial_text: str = None):
        self.error_type = error_type
        self.code = code
        self.message = message
        self.user_action = user_action or "Please retry later."
        self.raw_error = raw_error
        # Full, unclipped body of a truncated response.
        #
        # ``raw_error`` is capped at 500 chars by ``to_dict`` and was the only
        # place a truncated body survived — which meant a response that ran
        # past the output ceiling was thrown away whole: no issues, no
        # narrative, and the tokens already billed. A cut-off analysis is
        # still mostly a correct analysis, and the batch parser already knows
        # how to close unbalanced JSON, so the body is kept intact here for
        # ``analyze_batch`` to salvage. Only the truncation path sets this.
        self.partial_text = partial_text

    @classmethod
    def from_type(cls, error_type: str, raw_error: str = None):
        """Create an AIServiceError from an error_type key, using ERROR_TYPES for code/message."""
        error_info = cls.ERROR_TYPES.get(error_type, cls.ERROR_TYPES['unknown'])
        return cls(
            error_type=error_type,
            code=error_info['code'],
            message=error_info['message'],
            user_action=error_info['user_action'],
            raw_error=raw_error,
        )

    def get_display_status(self) -> str:
        """Return a status string suitable for model_name field display"""
        return f"FAILED ({self.code})"

    def get_user_message(self) -> str:
        """Return a user-friendly error message"""
        return f"{self.message} {self.user_action}"

    def to_dict(self) -> dict:
        return {
            'error_code': self.code,
            'error_message': self.message,
            'user_action': self.user_action,
            'raw_error': self.raw_error[:500] if self.raw_error else None
        }

    def __str__(self):
        return f"{self.code}: {self.message}"

class BaseProviderAdapter(ABC):
    """
    Abstract Base Class for all AI Provider Adapters.
    """

    @abstractmethod
    def generate(self, prompt: str, config: Dict[str, Any], api_key: str = None,
                 system_prefix: Optional[str] = None) -> Tuple[Optional[str], Optional[AIServiceError], int, int]:
        """
        Generate text response from the provider.

        Args:
            prompt: The dynamic per-call content (batch data, chat message, etc.)
            config: Dictionary from AIModelProvider.provider_config + defaults
            api_key: The decrypted API key to use
            system_prefix: Optional stable prefix that repeats across calls
                (JSON schema + analysis rules). When supplied, adapters
                route it to the provider's caching-aware channel:
                  - Claude: ``system=[{cache_control: ephemeral}]`` — 90% off
                    cached input tokens on Sonnet 5 (≥1024 token prefix).
                  - OpenAI / DeepSeek: ``messages[role=system]`` — provider-side
                    automatic caching kicks in on stable prefixes ≥1024 tokens.
                  - Gemini: prepended to ``contents`` (implicit caching min is
                    4096 on 3.5-flash, our prefix is ~2500 — no cache win, no
                    regression).
                Adapters with no caching path fall back to prepending.
                When None, adapters behave exactly as they did before this
                signature was added (backward compat for chat / manual paths).

        Returns:
            Tuple(response_text, error, tokens_input, tokens_output)
            - On success: (text, None, tokens_in, tokens_out)
            - On failure: (None, AIServiceError, tokens_in, tokens_out)

        Truncation contract:
            Adapters MUST check finish_reason after generation.
            If the response was truncated (e.g. Gemini MAX_TOKENS, OpenAI 'length'),
            return (None, AIServiceError('truncated', ..., partial_text[:2000]), tokens_in, tokens_out).
            Token counts MUST still be returned for billing accuracy.
        """
        pass

    @abstractmethod
    def normalize_error(self, raw_error: Exception) -> AIServiceError:
        """
        Convert provider-specific exception to standard AIServiceError.
        """
        pass
