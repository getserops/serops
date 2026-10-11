"""
Batch interval configuration helpers.

Provides per-organisation batch generation interval with Redis caching
and a system-level default fallback from the environment.
"""

import logging
import os

from django.core.cache import cache

logger = logging.getLogger(__name__)

# System-wide default: read from env (legacy compat), fallback 15 minutes
SYSTEM_DEFAULT_INTERVAL = int(os.getenv('BATCH_GENERATION_INTERVAL', 15))

_CACHE_KEY_PREFIX = 'batch_interval:org:'
_CACHE_TTL = 300  # 5 minutes


def get_batch_interval_for_org(organisation):
    """
    Return the batch generation interval (in minutes) for the given organisation.

    Checks Redis cache first, then DB, falls back to SYSTEM_DEFAULT_INTERVAL.
    """
    if organisation is None:
        return SYSTEM_DEFAULT_INTERVAL

    org_id = organisation.id if hasattr(organisation, 'id') else organisation
    cache_key = f'{_CACHE_KEY_PREFIX}{org_id}'

    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        from Data.models import RetentionPolicy
        policy = RetentionPolicy.objects.filter(organisation_id=org_id).only(
            'batch_generation_interval'
        ).first()
        interval = policy.batch_generation_interval if policy else SYSTEM_DEFAULT_INTERVAL
    except Exception:
        logger.warning('Failed to read batch interval for org %s, using default', org_id, exc_info=True)
        interval = SYSTEM_DEFAULT_INTERVAL

    cache.set(cache_key, interval, _CACHE_TTL)
    return interval


def invalidate_batch_interval_cache(organisation_id):
    """Remove cached interval so the next read picks up a fresh DB value."""
    cache.delete(f'{_CACHE_KEY_PREFIX}{organisation_id}')
