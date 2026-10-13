"""Per-project data-source capability registry.

**What this is for**

An org may enable only some of the five data sources SerOps consumes
(logs, metrics, code, cicd, traces). A logs-only user should never
see empty widgets, dead sidebar entries, or an AI prompt that
apologises for "no code changes in this time window" when they've
never connected an SCM.

**What this returns**

``enabled_capabilities_for(project)`` returns a ``frozenset`` — a
subset of the constant ``ALL_CAPABILITIES``. Every check downstream
(prompt builder, frontend gating, sentinel triggers) reads through
this one function, so adding a sixth source in the future means:

1. Add the constant to ``ALL_CAPABILITIES``.
2. Add its detector below.
3. Consumers automatically stay consistent.

**Derivation is live, not user-configured**

We infer from actual configured rows — not from a user-set flag.
Consequence: the moment a user configures Prometheus, ``metrics`` is
enabled; the moment they revoke every OTLP key AND remove every trace
provider, ``traces`` is disabled. No manual sync needed.

**Cost**

At most 5 EXISTS queries per call, all against small tables (unique
indexes on the join keys). Batches happen every 15 min per project,
UI reads once per session. No caching for now — add if profiling
shows it. Preferring simple + correct.

**Security**

All queries are org- or project-scoped via FK; there is no place a
caller could enumerate another org's config through this API.
"""

from __future__ import annotations

import logging
from typing import FrozenSet, Iterable, Optional

from django.core.cache import cache


logger = logging.getLogger(__name__)


LOGS = 'logs'
METRICS = 'metrics'
CODE = 'code'
CICD = 'cicd'
TRACES = 'traces'

ALL_CAPABILITIES: FrozenSet[str] = frozenset({LOGS, METRICS, CODE, CICD, TRACES})


# ---------------------------------------------------------------------------
# Cache layer (Q2.3)
# ---------------------------------------------------------------------------
#
# Each call to ``enabled_capabilities_for*`` used to fan out to 3-5
# EXISTS queries against small indexed tables. At MVP scale that's fine;
# at 100+ batches/min plus one lookup per authenticated UI request the
# waste compounds. We wrap the pure ``_uncached`` implementations behind
# Django's cache framework with signal-driven invalidation on the four
# model classes whose writes actually change what capabilities the org
# has — ``ObservabilityIntegration``, ``IngestKey``, ``SCMBinding``,
# ``CICDBinding``. Signals are registered in ``Organisations.signals``.
#
# Storage: frozenset isn't JSON-serialisable, so we store the sorted
# list and rehydrate. TTL is generous (1 hour) because invalidation is
# reactive — a stale cache only lingers when signals silently fail (a
# raw SQL update, a data migration bypassing ORM, etc.) or when the
# cache backend loses the delete. Both are exception paths; the TTL
# is the belt to the invalidation braces.
#
# Fail-open: any cache backend error falls back to the uncached path
# without raising. A Redis outage must not break capability lookups.

_CACHE_TTL_SECONDS = 3600
_ORG_CACHE_PREFIX = 'caps:org:'
_PROJ_CACHE_PREFIX = 'caps:proj:'


def _org_cache_key(org_id: int) -> str:
    return f'{_ORG_CACHE_PREFIX}{org_id}'


def _proj_cache_key(project_id: int) -> str:
    return f'{_PROJ_CACHE_PREFIX}{project_id}'


def _cache_get(key: str) -> Optional[FrozenSet[str]]:
    try:
        raw = cache.get(key)
    except Exception as exc:
        logger.warning('capability cache get failed for %s: %s', key, exc)
        return None
    if raw is None:
        return None
    # Only accept the list-of-strings shape we write. Anything else
    # (a truncated cache row, a legacy value from a redeploy) is
    # treated as a miss so the caller recomputes.
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        return None
    return frozenset(raw)


def _cache_set(key: str, value: FrozenSet[str]) -> None:
    try:
        cache.set(key, sorted(value), timeout=_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning('capability cache set failed for %s: %s', key, exc)


def invalidate_org(org_id: int) -> None:
    """Drop the cached org + every cached project under it.

    Called from :mod:`Organisations.signals` on any change that could
    flip an org-wide capability (``ObservabilityIntegration`` write,
    ``IngestKey`` write). Enumerates the org's project ids so a stale
    per-project entry can't survive a broad change.
    """
    if org_id is None:
        return
    keys = [_org_cache_key(org_id)]
    try:
        from Projects.models import Project
        project_ids = list(
            Project.objects.filter(organisation_id=org_id)
            .values_list('id', flat=True)
        )
    except Exception as exc:
        logger.warning('capability invalidate: project id lookup failed: %s', exc)
        project_ids = []
    keys.extend(_proj_cache_key(pid) for pid in project_ids)
    try:
        cache.delete_many(keys)
    except Exception as exc:
        logger.warning('capability cache delete_many failed: %s', exc)


def invalidate_project(project_id: int, org_id: Optional[int] = None) -> None:
    """Drop the cached project and, when known, the parent org's cache.

    The org-level result is a union that includes this project's
    code/cicd caps — a per-project binding flip has to invalidate the
    org-level answer too.
    """
    if project_id is None:
        return
    keys = [_proj_cache_key(project_id)]
    if org_id is not None:
        keys.append(_org_cache_key(org_id))
    try:
        cache.delete_many(keys)
    except Exception as exc:
        logger.warning('capability cache delete_many failed: %s', exc)


def clear_all() -> None:
    """Nuke every cached capability entry — used by tests and by the
    ``clear_capability_cache`` management path if we ever need it."""
    try:
        # cache.clear() would drop unrelated keys too; we don't want
        # to torpedo the AI circuit breaker's cache. Enumerate what
        # we own and delete only that.
        from Projects.models import Project
        from Organisations.models import Organisations
        keys = [
            _org_cache_key(org_id)
            for org_id in Organisations.objects.values_list('id', flat=True)
        ]
        keys.extend(
            _proj_cache_key(pid)
            for pid in Project.objects.values_list('id', flat=True)
        )
        cache.delete_many(keys)
    except Exception as exc:
        logger.warning('capability cache clear_all failed: %s', exc)


# ---------------------------------------------------------------------------
# Public API — cached wrappers over the pure detectors below.
# ---------------------------------------------------------------------------


def enabled_capabilities_for(project) -> FrozenSet[str]:
    """
    Return the set of data-source capabilities available for ``project``.

    A capability is "available" if the org (or project) has at least one
    actively-configured integration for it. Returns the empty frozenset
    when ``project`` or its ``organisation`` is falsy.

    Cached per-project with signal-driven invalidation. On cache miss
    the underlying detectors run and the result is stored for reuse.
    """
    if project is None:
        return frozenset()
    org = getattr(project, 'organisation', None)
    if org is None:
        return frozenset()

    key = _proj_cache_key(project.id)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    result = _enabled_capabilities_for_uncached(project, org)
    _cache_set(key, result)
    return result


def enabled_capabilities_for_org(organisation) -> FrozenSet[str]:
    """
    Union of capabilities across all projects in an organisation.

    Used by the frontend to gate sidebar entries + dashboard cards
    (which are org-scoped, not project-scoped).

    Cached per-org with signal-driven invalidation.
    """
    if organisation is None:
        return frozenset()

    key = _org_cache_key(organisation.id)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    result = _enabled_capabilities_for_org_uncached(organisation)
    _cache_set(key, result)
    return result


# ---------------------------------------------------------------------------
# Uncached implementations — the source of truth. Callers that must
# bypass the cache (tests asserting DB state, admin health-check
# commands) can import these directly.
# ---------------------------------------------------------------------------


def _enabled_capabilities_for_uncached(project, org) -> FrozenSet[str]:
    enabled = set()
    if _has_logs(org):
        enabled.add(LOGS)
    if _has_metrics(org):
        enabled.add(METRICS)
    if _has_code(project):
        enabled.add(CODE)
    if _has_cicd(project):
        enabled.add(CICD)
    if _has_traces(org):
        enabled.add(TRACES)
    return frozenset(enabled)


def _enabled_capabilities_for_org_uncached(organisation) -> FrozenSet[str]:
    enabled = set()
    if _has_logs(organisation):
        enabled.add(LOGS)
    if _has_metrics(organisation):
        enabled.add(METRICS)
    if _has_traces(organisation):
        enabled.add(TRACES)
    # Code / CI-CD are per-project via bindings, so we union across.
    from Projects.models import Project
    project_ids = list(Project.objects.filter(organisation=organisation).values_list('id', flat=True))
    if project_ids and _any_project_has_code(project_ids):
        enabled.add(CODE)
    if project_ids and _any_project_has_cicd(project_ids):
        enabled.add(CICD)
    return frozenset(enabled)


# ---------------------------------------------------------------------------
# Per-source detectors — kept small and grep-able. Each is one query.
# ---------------------------------------------------------------------------


def _has_logs(organisation) -> bool:
    from integrations.models import ObservabilityIntegration
    return ObservabilityIntegration.objects.filter(
        organisation=organisation,
        is_active=True,
        capabilities__contains=['logs'],
    ).exists()


def _has_metrics(organisation) -> bool:
    from integrations.models import ObservabilityIntegration
    return ObservabilityIntegration.objects.filter(
        organisation=organisation,
        is_active=True,
        capabilities__contains=['metrics'],
    ).exists()


def _has_traces(organisation) -> bool:
    """
    Traces are on if EITHER path is live:

    * OTLP receiver — at least one active IngestKey for the org, OR
    * External adapter — an ObservabilityIntegration exposing the
      ``traces`` capability (Jaeger, Zipkin, Datadog APM).
    """
    from traces.models import IngestKey
    if IngestKey.objects.filter(organisation=organisation, is_active=True).exists():
        return True
    from integrations.models import ObservabilityIntegration
    return ObservabilityIntegration.objects.filter(
        organisation=organisation,
        is_active=True,
        capabilities__contains=['traces'],
    ).exists()


def _has_code(project) -> bool:
    """A project has code visibility if any of its services has an SCMBinding."""
    from Projects.models import SCMBinding
    return SCMBinding.objects.filter(
        project_service__project=project,
    ).exists()


def _has_cicd(project) -> bool:
    """A project has CI/CD visibility if any of its services has a CICDBinding."""
    from Projects.models import CICDBinding
    return CICDBinding.objects.filter(
        project_service__project=project,
    ).exists()


def _any_project_has_code(project_ids) -> bool:
    from Projects.models import SCMBinding
    return SCMBinding.objects.filter(
        project_service__project_id__in=project_ids,
    ).exists()


def _any_project_has_cicd(project_ids) -> bool:
    from Projects.models import CICDBinding
    return CICDBinding.objects.filter(
        project_service__project_id__in=project_ids,
    ).exists()
