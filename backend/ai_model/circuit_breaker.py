"""
Circuit Breaker for AI Provider Calls

Implements the Circuit Breaker pattern to prevent cascading failures
when AI providers are experiencing quota issues or outages.

States:
- CLOSED: Normal operation, requests flow through
- OPEN: Provider is unavailable, requests fail fast or use fallback
- HALF_OPEN: Testing if provider has recovered

Usage:
    from ai_model.circuit_breaker import AICircuitBreaker

    breaker = AICircuitBreaker('gemini')

    if breaker.can_execute():
        try:
            result = call_gemini_api()
            breaker.record_success()
        except QuotaError:
            breaker.record_failure('quota_exceeded')
    else:
        # Use fallback provider
        result = call_deepseek_api()
"""

import logging
import time
from django.core.cache import cache
from enum import Enum
from dataclasses import dataclass
from typing import Tuple

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitConfig:
    """Configuration for a circuit breaker."""
    failure_threshold: int = 3
    recovery_timeout: int = 300
    half_open_max_calls: int = 1
    success_threshold: int = 1

    # Error types that trip the circuit
    tripping_errors: tuple = ('quota_exceeded', 'rate_limited', 'timeout')


# Hard defaults used when no DB config exists
PROVIDER_CONFIGS = {
    'gemini': CircuitConfig(
        failure_threshold=2,
        recovery_timeout=300,
    ),
    'deepseek': CircuitConfig(
        failure_threshold=3,
        recovery_timeout=120,
    ),
    'claude': CircuitConfig(
        failure_threshold=2,
        recovery_timeout=180,
    ),
    'openai': CircuitConfig(
        failure_threshold=2,
        recovery_timeout=180,
    ),
}

# In-memory cache for DB-driven configs
_db_configs_cache = {}
_db_configs_timestamp = 0
_DB_CACHE_TTL = 300  # 5 minutes


def _get_circuit_config(provider: str) -> CircuitConfig:
    """Get circuit breaker config for a provider, preferring DB values over hard defaults."""
    global _db_configs_cache, _db_configs_timestamp

    # Refresh DB cache if stale
    if time.time() - _db_configs_timestamp > _DB_CACHE_TTL:
        try:
            from org_settings.models import AIModelProvider
            new_cache = {}
            for p in AIModelProvider.objects.filter(is_active=True):
                if p.circuit_config:
                    cc = p.circuit_config
                    new_cache[p.name] = CircuitConfig(
                        failure_threshold=cc.get('failure_threshold', 3),
                        recovery_timeout=cc.get('recovery_timeout', 300),
                        half_open_max_calls=cc.get('half_open_max_calls', 1),
                        success_threshold=cc.get('success_threshold', 1),
                    )
            _db_configs_cache = new_cache
            _db_configs_timestamp = time.time()
        except Exception as e:
            logger.warning(f"Could not load circuit configs from DB: {e}")

    return (_db_configs_cache.get(provider.lower())
            or PROVIDER_CONFIGS.get(provider.lower())
            or CircuitConfig())


class AICircuitBreaker:
    """
    Circuit breaker for AI provider API calls.

    Uses Django cache (Redis recommended) for distributed state.
    """

    def __init__(self, provider: str, config: CircuitConfig = None):
        self.provider = provider.lower()
        self.config = config or _get_circuit_config(self.provider)
        self._cache_prefix = f"ai_circuit:{self.provider}"

    # =========================================================================
    # Cache Key Helpers
    # =========================================================================

    @property
    def _state_key(self) -> str:
        return f"{self._cache_prefix}:state"

    @property
    def _failure_count_key(self) -> str:
        return f"{self._cache_prefix}:failures"

    @property
    def _opened_at_key(self) -> str:
        return f"{self._cache_prefix}:opened_at"

    @property
    def _half_open_calls_key(self) -> str:
        return f"{self._cache_prefix}:half_open_calls"

    @property
    def _success_count_key(self) -> str:
        return f"{self._cache_prefix}:successes"

    # =========================================================================
    # State Management
    # =========================================================================

    def get_state(self) -> CircuitState:
        """Get current circuit state, checking for automatic transitions."""
        state_str = cache.get(self._state_key, CircuitState.CLOSED.value)

        if state_str == CircuitState.OPEN.value:
            opened_at = cache.get(self._opened_at_key, 0)
            if time.time() - opened_at >= self.config.recovery_timeout:
                self._transition_to_half_open()
                return CircuitState.HALF_OPEN

        return CircuitState(state_str)

    def _set_state(self, state: CircuitState, ttl: int = 3600):
        cache.set(self._state_key, state.value, ttl)
        logger.info(f"Circuit breaker [{self.provider}] -> {state.value}")

    def _transition_to_open(self, reason: str = "unknown"):
        now = time.time()
        ttl = self.config.recovery_timeout * 2

        cache.set(self._state_key, CircuitState.OPEN.value, ttl)
        cache.set(self._opened_at_key, now, ttl)
        cache.delete(self._failure_count_key)
        cache.delete(self._success_count_key)

        logger.warning(
            f"Circuit OPENED for [{self.provider}] - Reason: {reason}. "
            f"Will try recovery in {self.config.recovery_timeout}s"
        )

    def _transition_to_half_open(self):
        ttl = self.config.recovery_timeout

        cache.set(self._state_key, CircuitState.HALF_OPEN.value, ttl)
        cache.set(self._half_open_calls_key, 0, ttl)
        cache.set(self._success_count_key, 0, ttl)

        logger.info(f"Circuit HALF-OPEN for [{self.provider}] - Testing recovery...")

    def _transition_to_closed(self):
        cache.delete(self._state_key)
        cache.delete(self._opened_at_key)
        cache.delete(self._failure_count_key)
        cache.delete(self._half_open_calls_key)
        cache.delete(self._success_count_key)

        logger.info(f"Circuit CLOSED for [{self.provider}] - Provider recovered!")

    # =========================================================================
    # Public API
    # =========================================================================

    def can_execute(self) -> Tuple[bool, str]:
        """Check if a request can be made."""
        state = self.get_state()

        if state == CircuitState.CLOSED:
            return True, "circuit_closed"

        if state == CircuitState.OPEN:
            remaining = self._get_remaining_recovery_time()
            return False, f"circuit_open (recovery in {remaining}s)"

        if state == CircuitState.HALF_OPEN:
            current_calls = cache.get(self._half_open_calls_key, 0)
            if current_calls < self.config.half_open_max_calls:
                cache.incr(self._half_open_calls_key)
                return True, "circuit_half_open_testing"
            return False, "circuit_half_open_limit_reached"

        return True, "unknown_state"

    def record_success(self):
        """Record a successful API call."""
        state = self.get_state()

        if state == CircuitState.HALF_OPEN:
            success_count = cache.incr(self._success_count_key)
            if success_count >= self.config.success_threshold:
                self._transition_to_closed()

        elif state == CircuitState.CLOSED:
            cache.delete(self._failure_count_key)

    def record_failure(self, error_type: str = "unknown"):
        """Record a failed API call."""
        state = self.get_state()

        if error_type not in self.config.tripping_errors:
            logger.debug(f"Error type '{error_type}' does not trip circuit")
            return

        if state == CircuitState.HALF_OPEN:
            self._transition_to_open(reason=f"half_open_failure:{error_type}")

        elif state == CircuitState.CLOSED:
            failure_count = cache.incr(self._failure_count_key)
            cache.expire(self._failure_count_key, 60)

            if failure_count >= self.config.failure_threshold:
                self._transition_to_open(reason=error_type)
            else:
                logger.warning(
                    f"Circuit [{self.provider}] failure {failure_count}/{self.config.failure_threshold}"
                )

    def force_open(self, duration: int = None):
        """Manually open the circuit."""
        duration = duration or self.config.recovery_timeout
        self._transition_to_open(reason="manual_force_open")

    def force_close(self):
        """Manually close the circuit."""
        self._transition_to_closed()

    def get_status(self) -> dict:
        """Get current circuit status for monitoring."""
        state = self.get_state()

        status = {
            'provider': self.provider,
            'state': state.value,
            'failure_count': cache.get(self._failure_count_key, 0),
            'config': {
                'failure_threshold': self.config.failure_threshold,
                'recovery_timeout': self.config.recovery_timeout,
            }
        }

        if state == CircuitState.OPEN:
            status['remaining_recovery_seconds'] = self._get_remaining_recovery_time()

        return status

    def _get_remaining_recovery_time(self) -> int:
        opened_at = cache.get(self._opened_at_key, 0)
        if not opened_at:
            return 0
        elapsed = time.time() - opened_at
        remaining = max(0, self.config.recovery_timeout - int(elapsed))
        return remaining


# =============================================================================
# Convenience Functions
# =============================================================================

def get_circuit_breaker(provider: str) -> AICircuitBreaker:
    """Get a circuit breaker for a provider."""
    return AICircuitBreaker(provider)


def get_all_circuit_status() -> dict:
    """Get status of all active provider circuits (DB-driven)."""
    try:
        from org_settings.models import AIModelProvider
        providers = list(AIModelProvider.objects.filter(is_active=True).values_list('name', flat=True))
    except Exception:
        providers = list(PROVIDER_CONFIGS.keys())
    return {
        provider: AICircuitBreaker(provider).get_status()
        for provider in providers
    }


def reset_all_circuits():
    """Reset all circuits to closed state."""
    try:
        from org_settings.models import AIModelProvider
        providers = list(AIModelProvider.objects.filter(is_active=True).values_list('name', flat=True))
    except Exception:
        providers = list(PROVIDER_CONFIGS.keys())
    for provider in providers:
        AICircuitBreaker(provider).force_close()
    logger.info("All AI circuits reset to CLOSED")
