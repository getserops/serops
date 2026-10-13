"""
Rate Limiter for AI Provider Calls

Implements token bucket rate limiting to prevent quota exhaustion
and ensure fair usage across multiple organisations.

Features:
- Per-provider rate limits (DB-driven with in-memory cache)
- Per-organisation tracking (optional)
- Sliding window algorithm
- Redis-backed for distributed environments

Usage:
    from ai_model.rate_limiter import AIRateLimiter

    limiter = AIRateLimiter()

    if limiter.acquire('gemini'):
        result = call_gemini_api()
    else:
        wait_time = limiter.get_wait_time('gemini')
        # Either wait or use fallback
"""

import logging
import time
from django.core.cache import cache
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Rate limit configuration for a provider."""
    requests_per_minute: int
    requests_per_hour: int = 0        # 0 = no hourly limit
    tokens_per_minute: int = 0        # 0 = no token limit (for future use)
    burst_allowance: int = 0          # Extra requests allowed in burst


# Hard defaults used when no DB config exists
PROVIDER_LIMITS = {
    'gemini': RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=200,
        burst_allowance=2,
    ),
    'deepseek': RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=500,
        burst_allowance=5,
    ),
    'claude': RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=300,
        burst_allowance=3,
    ),
    'openai': RateLimitConfig(
        requests_per_minute=20,
        requests_per_hour=300,
        burst_allowance=3,
    ),
}

# In-memory cache for DB-driven limits
_db_limits_cache = {}
_db_limits_timestamp = 0
_DB_CACHE_TTL = 300  # 5 minutes


def _get_limits(provider: str) -> RateLimitConfig:
    """Get rate limit config for a provider, preferring DB values over hard defaults."""
    global _db_limits_cache, _db_limits_timestamp

    # Refresh DB cache if stale
    if time.time() - _db_limits_timestamp > _DB_CACHE_TTL:
        try:
            from org_settings.models import AIModelProvider
            new_cache = {}
            for p in AIModelProvider.objects.filter(is_active=True):
                if p.rate_limits:
                    rl = p.rate_limits
                    new_cache[p.name] = RateLimitConfig(
                        requests_per_minute=rl.get('requests_per_minute', rl.get('rpm', 10)),
                        requests_per_hour=rl.get('requests_per_hour', rl.get('rph', 0)),
                        tokens_per_minute=rl.get('tokens_per_minute', rl.get('tpm', 0)),
                        burst_allowance=rl.get('burst_allowance', 0),
                    )
            _db_limits_cache = new_cache
            _db_limits_timestamp = time.time()
        except Exception as e:
            logger.warning(f"Could not load rate limits from DB: {e}")

    # Priority: DB cache > hard defaults > generic fallback
    return (_db_limits_cache.get(provider.lower())
            or PROVIDER_LIMITS.get(provider.lower())
            or RateLimitConfig(requests_per_minute=10))


class AIRateLimiter:
    """
    Rate limiter for AI provider API calls.

    Uses sliding window counter algorithm with Django cache (Redis recommended).
    """

    def __init__(self, organisation_id: str = None):
        self.organisation_id = organisation_id
        self._cache_prefix = "ai_rate"

    # =========================================================================
    # Cache Key Helpers
    # =========================================================================

    def _minute_key(self, provider: str) -> str:
        minute = int(time.time() // 60)
        org_part = f":{self.organisation_id}" if self.organisation_id else ""
        return f"{self._cache_prefix}:{provider}:m:{minute}{org_part}"

    def _hour_key(self, provider: str) -> str:
        hour = int(time.time() // 3600)
        org_part = f":{self.organisation_id}" if self.organisation_id else ""
        return f"{self._cache_prefix}:{provider}:h:{hour}{org_part}"

    def _last_request_key(self, provider: str) -> str:
        org_part = f":{self.organisation_id}" if self.organisation_id else ""
        return f"{self._cache_prefix}:{provider}:last{org_part}"

    # =========================================================================
    # Rate Limit Checking
    # =========================================================================

    def acquire(self, provider: str, cost: int = 1) -> bool:
        """
        Try to acquire a rate limit slot.

        Returns:
            bool: True if request is allowed, False if rate limited
        """
        config = _get_limits(provider)

        # Check per-minute limit
        minute_key = self._minute_key(provider)
        current_minute = cache.get(minute_key, 0)

        effective_limit = config.requests_per_minute + config.burst_allowance

        if current_minute + cost > effective_limit:
            logger.warning(
                f"Rate limit reached for [{provider}]: "
                f"{current_minute}/{config.requests_per_minute} RPM"
            )
            return False

        # Check per-hour limit if configured
        if config.requests_per_hour > 0:
            hour_key = self._hour_key(provider)
            current_hour = cache.get(hour_key, 0)

            if current_hour + cost > config.requests_per_hour:
                logger.warning(
                    f"Hourly rate limit reached for [{provider}]: "
                    f"{current_hour}/{config.requests_per_hour} RPH"
                )
                return False

        # Acquire the slot
        cache.set(minute_key, current_minute + cost, 120)

        if config.requests_per_hour > 0:
            hour_key = self._hour_key(provider)
            current_hour = cache.get(hour_key, 0)
            cache.set(hour_key, current_hour + cost, 3700)

        cache.set(self._last_request_key(provider), time.time(), 300)

        return True

    def get_wait_time(self, provider: str) -> int:
        """Get seconds to wait before next request is allowed."""
        config = _get_limits(provider)

        minute_key = self._minute_key(provider)
        current = cache.get(minute_key, 0)

        if current < config.requests_per_minute:
            return 0

        return 60 - int(time.time() % 60)

    def get_remaining(self, provider: str) -> Tuple[int, int]:
        """Get remaining request allowance: (remaining_minute, remaining_hour)."""
        config = _get_limits(provider)

        minute_key = self._minute_key(provider)
        current_minute = cache.get(minute_key, 0)
        remaining_minute = max(0, config.requests_per_minute - current_minute)

        remaining_hour = -1
        if config.requests_per_hour > 0:
            hour_key = self._hour_key(provider)
            current_hour = cache.get(hour_key, 0)
            remaining_hour = max(0, config.requests_per_hour - current_hour)

        return remaining_minute, remaining_hour

    def get_status(self, provider: str) -> dict:
        """Get current rate limit status for monitoring."""
        config = _get_limits(provider)
        remaining_minute, remaining_hour = self.get_remaining(provider)

        return {
            'provider': provider,
            'organisation_id': self.organisation_id,
            'limits': {
                'requests_per_minute': config.requests_per_minute,
                'requests_per_hour': config.requests_per_hour,
            },
            'current': {
                'remaining_minute': remaining_minute,
                'remaining_hour': remaining_hour if remaining_hour >= 0 else 'unlimited',
            },
            'wait_time_seconds': self.get_wait_time(provider),
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def check_rate_limit(provider: str, organisation_id: str = None) -> Tuple[bool, int]:
    """Quick check if a request can be made."""
    limiter = AIRateLimiter(organisation_id)
    allowed = limiter.acquire(provider)
    wait = 0 if allowed else limiter.get_wait_time(provider)
    return allowed, wait


def get_all_rate_status() -> dict:
    """Get rate limit status for all active providers (DB-driven)."""
    limiter = AIRateLimiter()
    try:
        from org_settings.models import AIModelProvider
        providers = list(AIModelProvider.objects.filter(is_active=True).values_list('name', flat=True))
    except Exception:
        providers = list(PROVIDER_LIMITS.keys())
    return {
        provider: limiter.get_status(provider)
        for provider in providers
    }
