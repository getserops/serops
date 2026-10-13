"""
Integration Adapter Registry.

Dynamically loads and caches LogProvider / MetricProvider adapters.
Queries the unified ObservabilityIntegration model by capability.
"""

import importlib
import json
import logging
from typing import Optional

from .base import LogProvider, MetricProvider, TraceProvider

logger = logging.getLogger(__name__)


class IntegrationRegistry:
    """
    Load and cache integration adapters by dotted class path.

    Cache keys are scoped by (class_path, org_id, config_hash) to ensure
    per-org isolation.
    """

    _cache: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @classmethod
    def get_log_provider(cls, class_path: str, config: dict = None, org_id=None) -> LogProvider:
        """Load a LogProvider adapter by class path."""
        return cls._load_adapter(class_path, LogProvider, config, org_id=org_id)

    @classmethod
    def get_metric_provider(cls, class_path: str, config: dict = None, org_id=None) -> MetricProvider:
        """Load a MetricProvider adapter by class path."""
        return cls._load_adapter(class_path, MetricProvider, config, org_id=org_id)

    @classmethod
    def get_trace_provider(cls, class_path: str, config: dict = None, org_id=None) -> TraceProvider:
        """Load a TraceProvider adapter by class path."""
        return cls._load_adapter(class_path, TraceProvider, config, org_id=org_id)

    @classmethod
    def get_trace_provider_for_org(cls, organisation, cluster=None,
                                     deployment=None) -> Optional[TraceProvider]:
        """
        Return the configured TraceProvider for an organisation, or
        ``None`` if none is configured. Unlike logs/metrics we don't
        raise — the AI enrichment path treats an absent trace provider
        as "no external trace source, use only OTLP-ingested data".

        Batch 49 — accepts optional ``deployment`` for scope-aware
        integration selection. Falls back to cluster-only when
        deployment is None (backwards-compat).
        """
        from .models import ObservabilityIntegration
        org_id = getattr(organisation, 'id', None)
        integration = cls._best_integration(
            organisation, 'traces', cluster=cluster, deployment=deployment,
        )
        if not integration or not integration.trace_adapter_class:
            return None
        try:
            return cls.get_trace_provider(
                integration.trace_adapter_class,
                integration.get_config(),
                org_id=org_id,
            )
        except (ImportError, ValueError, TypeError) as exc:
            logger.warning(
                'Trace provider load failed for org=%s (%s): %s',
                org_id, integration.trace_adapter_class, exc,
            )
            return None

    @classmethod
    def get_log_provider_for_org(cls, organisation, cluster=None,
                                   deployment=None) -> LogProvider:
        """
        Get the configured LogProvider for an organisation.

        Batch 49 — deployment-aware. When ``deployment`` is provided
        the integration is picked via full scope-match scoring
        (cluster + env + region + namespace) with priority_tier
        failover. When only ``cluster`` is provided (pre-Batch 49
        callers), behaves as the Batch 17 cluster-preferred lookup.
        When both are None, unscoped fallback wins (single-cluster
        installs are unaffected).

        If the highest-scoring integration's adapter fails to load
        (missing optional dep like ``boto3``, or a config error), we
        fall through to the next-priority integration instead of
        raising — matches ``get_trace_provider_for_org`` behaviour.
        """
        return cls._resolve_provider_for_org(
            organisation, 'logs', cluster=cluster, deployment=deployment,
            loader=cls.get_log_provider,
            adapter_attr='log_adapter_class',
            not_found_msg='No Log Integration configured for organisation',
        )

    @classmethod
    def get_metric_provider_for_org(cls, organisation, cluster=None,
                                      deployment=None) -> MetricProvider:
        """
        Get the configured MetricProvider for an organisation.

        See ``get_log_provider_for_org`` for the deployment/cluster
        + failover semantics — identical.
        """
        return cls._resolve_provider_for_org(
            organisation, 'metrics', cluster=cluster, deployment=deployment,
            loader=cls.get_metric_provider,
            adapter_attr='metric_adapter_class',
            not_found_msg='No Metric Integration configured for organisation',
        )

    @classmethod
    def _resolve_provider_for_org(cls, organisation, capability, cluster,
                                    deployment, loader, adapter_attr,
                                    not_found_msg):
        """Shared logs/metrics resolver with failover on adapter load errors.

        Walks integrations in priority order; skips ones whose adapter
        raises ``ImportError`` (missing optional dep like ``boto3``) or
        ``ValueError`` (bad config). Raises ``ValueError`` only when
        the whole chain is exhausted with no adapter loadable.
        """
        org_id = getattr(organisation, 'id', None)
        skip_ids: list = []
        last_load_exc = None
        while True:
            integration = cls._first_matching_integration(
                organisation, capability, cluster=cluster,
                deployment=deployment, skip_ids=skip_ids or None,
            )
            if not integration:
                if last_load_exc is not None:
                    raise ValueError(
                        f"{not_found_msg} {org_id}: all candidate integrations "
                        f"failed to load (last error: {last_load_exc})"
                    )
                raise ValueError(f"{not_found_msg} {org_id}")
            try:
                return loader(
                    getattr(integration, adapter_attr),
                    integration.get_config(),
                    org_id=org_id,
                )
            except (ImportError, ValueError, TypeError) as exc:
                logger.warning(
                    "%s adapter load failed for org=%s integration=%s (%s): %s — "
                    "trying next-priority integration",
                    capability, org_id, integration.id,
                    getattr(integration, adapter_attr), exc,
                )
                skip_ids.append(integration.id)
                last_load_exc = exc

    # Provider-priority Case expression used as an internal tiebreaker
    # AFTER scope-match scoring + priority_tier. Self-hosted providers
    # are preferred over managed services because they typically have
    # lower per-call cost + no API-key dependency.
    _PROVIDER_TIEBREAK = None  # lazy-init in _get_provider_tiebreak

    @classmethod
    def _get_provider_tiebreak(cls):
        if cls._PROVIDER_TIEBREAK is None:
            from django.db.models import Case, When, Value, IntegerField
            cls._PROVIDER_TIEBREAK = Case(
                When(provider='elasticsearch', then=Value(0)),
                When(provider='opensearch', then=Value(1)),
                When(provider='loki', then=Value(2)),
                When(provider='splunk', then=Value(3)),
                When(provider='prometheus', then=Value(0)),
                When(provider='victoriametrics', then=Value(1)),
                When(provider='mimir', then=Value(2)),
                When(provider='jaeger', then=Value(0)),
                When(provider='zipkin', then=Value(1)),
                When(provider='tempo', then=Value(0)),
                default=Value(10),
                output_field=IntegerField(),
            )
        return cls._PROVIDER_TIEBREAK

    # Priority-tier ordering for failover chain — primary first, then
    # fallback, then tertiary. Kept as a Django Case expression for
    # DB-level ORDER BY (avoids Python-side sort on a queryset).
    @classmethod
    def _get_tier_priority(cls):
        from django.db.models import Case, When, Value, IntegerField
        return Case(
            When(priority_tier='primary', then=Value(0)),
            When(priority_tier='fallback', then=Value(1)),
            When(priority_tier='tertiary', then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )

    @classmethod
    def _best_integration(cls, organisation, capability: str, cluster=None,
                           deployment=None):
        """Pick the best integration for a capability using scope-match scoring.

        Batch 49 rewrite. Behaviour:

        1. **Scope-match score** — count how many of the deployment's
           dimensions (cluster, env, region, namespace) the integration's
           IntegrationScope matches. Wildcards (NULL / empty string on
           the scope side) match everything. Higher score wins.

        2. **Precedence tiebreaker** — if two integrations have the same
           match count, prefer the one that matched on the MORE-
           IMPORTANT field. Order: cluster > env > region > namespace.

        3. **priority_tier** — primary before fallback before tertiary.
           Failover uses this same ordering (see
           ``iter_integrations_for_failover`` for the chain).

        4. **Provider tiebreak** — self-hosted (ES/Prom/etc) preferred
           over managed (Datadog/CloudWatch). Same as pre-Batch 49.

        Backwards-compat: when ``deployment`` is None but ``cluster`` is
        provided, we synthesize a minimal deployment shape from
        (cluster, env=None, region='', namespace='') so old callers
        (pre-Batch 49) keep working with identical semantics — the
        cluster-scoped preference falls out of the match-scoring for
        free.

        When BOTH are None (pre-multi-cluster callers), match-scoring
        finds any active integration for the capability, preferring
        unscoped fallbacks so single-cluster installs are unaffected.
        """
        best = cls._first_matching_integration(
            organisation, capability, cluster=cluster, deployment=deployment,
        )
        return best

    @classmethod
    def _first_matching_integration(cls, organisation, capability: str,
                                     cluster=None, deployment=None,
                                     skip_ids=None):
        """Return the highest-scoring integration, optionally skipping
        already-tried ones (used by the failover chain iterator)."""
        from .models import ObservabilityIntegration

        base_qs = ObservabilityIntegration.objects.filter(
            organisation=organisation,
            is_active=True,
            capabilities__contains=[capability],
        ).select_related('scope', 'cluster')
        if skip_ids:
            base_qs = base_qs.exclude(pk__in=skip_ids)

        # Materialise into Python so match-scoring can be exact per-
        # candidate. Integration counts per org are small (single
        # digits typically, low tens at the extreme) — safe.
        candidates = list(base_qs)
        if not candidates:
            return None

        # Extract deployment dimensions (cluster, env-name, region, namespace).
        dep_cluster_id, dep_env, dep_region, dep_namespace = cls._deployment_dimensions(
            deployment=deployment, cluster=cluster,
        )

        # Score each candidate.
        provider_rank = {
            'elasticsearch': 0, 'opensearch': 1, 'loki': 2, 'splunk': 3,
            'prometheus': 0, 'victoriametrics': 1, 'mimir': 2,
            'jaeger': 0, 'zipkin': 1, 'tempo': 0,
        }
        tier_rank = {'primary': 0, 'fallback': 1, 'tertiary': 2}

        def score(integ):
            match_count, precedence = cls._score_scope(
                integ, dep_cluster_id, dep_env, dep_region, dep_namespace,
            )
            # Lower tuple = better. Negate match-count so higher matches
            # sort first. Precedence is already "lower = better field".
            return (
                -match_count,                           # more matches → better
                precedence,                             # tiebreak on which field matched
                tier_rank.get(integ.priority_tier, 3),  # primary first
                provider_rank.get(integ.provider, 10),  # self-hosted first
                integ.pk,                                # stable final tiebreak
            )

        candidates.sort(key=score)
        return candidates[0]

    @classmethod
    def _deployment_dimensions(cls, deployment=None, cluster=None):
        """Extract (cluster_id, env_name, region, namespace) from either
        a ProjectDeployment or a bare cluster (backwards-compat path)."""
        if deployment is not None:
            return (
                deployment.cluster_id,
                deployment.environment.name if deployment.environment_id else '',
                deployment.region or '',
                deployment.namespace or '',
            )
        if cluster is not None:
            return (getattr(cluster, 'id', cluster), '', '', '')
        return (None, '', '', '')

    @classmethod
    def _score_scope(cls, integ, dep_cluster_id, dep_env, dep_region, dep_namespace):
        """Return (match_count, precedence) for one integration vs a deployment.

        Wildcard-friendly: if the integration's scope field is empty /
        null, it matches anything on that dimension. If it's set, it
        must equal the deployment's value to count.

        ``precedence`` is a small integer where LOWER = matched on
        more-important field. Used to break ties when two integrations
        have the same match_count. Order: cluster > env > region > namespace.
        We encode as 0000-1111 bitmask (cluster=8, env=4, region=2, ns=1),
        THEN invert so lower value = better precedence.
        """
        # Read scope; if no scope row yet (pre-migration state, rare),
        # fall back to integration.cluster only.
        scope = getattr(integ, 'scope', None)
        scope_cluster_id = scope.cluster_id if scope else integ.cluster_id
        scope_env = (scope.environment if scope else '') or ''
        scope_region = (scope.region if scope else '') or ''
        scope_namespace = (scope.namespace if scope else '') or ''

        match_count = 0
        precedence_bits = 0  # weight matched fields by importance

        # cluster (weight 8)
        if not scope_cluster_id:
            # Wildcard match — counts as a match. Weight 0 so it doesn't
            # win against integrations that explicitly matched the cluster.
            match_count += 1
        elif scope_cluster_id == dep_cluster_id:
            match_count += 1
            precedence_bits |= 8

        # env (weight 4)
        if not scope_env:
            match_count += 1
        elif scope_env == dep_env:
            match_count += 1
            precedence_bits |= 4

        # region (weight 2)
        if not scope_region:
            match_count += 1
        elif scope_region == dep_region:
            match_count += 1
            precedence_bits |= 2

        # namespace (weight 1)
        if not scope_namespace:
            match_count += 1
        elif scope_namespace == dep_namespace:
            match_count += 1
            precedence_bits |= 1

        # Explicit-match integration MUST beat wildcard-only. Invert
        # precedence_bits so higher weight = lower (better) score.
        # Range: 0 (matched all 4 fields explicitly) → 15 (matched
        # nothing explicitly, all wildcards).
        precedence = 15 - precedence_bits

        return match_count, precedence

    @classmethod
    def iter_integrations_for_failover(cls, organisation, capability: str,
                                        cluster=None, deployment=None,
                                        max_tries=3):
        """Yield integrations in failover order.

        Callers wrap their query call in a for-loop, ``try``/``except``
        adapter errors, and ``continue`` to the next integration on
        failure. Yields up to ``max_tries`` (default 3, matching the
        primary/fallback/tertiary tier ceiling) unique integrations
        ordered by scope-match score.
        """
        tried = set()
        for _ in range(max_tries):
            integ = cls._first_matching_integration(
                organisation, capability,
                cluster=cluster, deployment=deployment,
                skip_ids=tried,
            )
            if integ is None:
                return
            tried.add(integ.pk)
            yield integ

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @classmethod
    def clear_cache(cls, org_id=None):
        """
        Clear the adapter cache.

        If *org_id* is given, only invalidate entries for that org.
        """
        if org_id is not None:
            prefix = f':org={org_id}:'
            keys_to_remove = [k for k in cls._cache if prefix in k]
            for k in keys_to_remove:
                del cls._cache[k]
            logger.debug(
                'Cleared %d cached adapters for org_id=%s', len(keys_to_remove), org_id
            )
        else:
            cls._cache.clear()
            logger.debug('Cleared all cached adapters')

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    def _make_cache_key(cls, class_path: str, config: dict = None, org_id=None) -> str:
        config_fingerprint = (
            json.dumps(config, sort_keys=True, default=str) if config else 'default'
        )
        return f'{class_path}:org={org_id}:{config_fingerprint}'

    @classmethod
    def _load_adapter(cls, class_path: str, expected_type, config: dict = None, org_id=None):
        cache_key = cls._make_cache_key(class_path, config, org_id)

        if cache_key in cls._cache:
            return cls._cache[cache_key]

        # Security: only allow loading from integrations.adapters
        if not class_path.startswith('integrations.adapters.'):
            raise ValueError(
                f'Security: cannot load adapter from outside integrations.adapters ({class_path})'
            )

        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            adapter_class = getattr(module, class_name)

            if not issubclass(adapter_class, expected_type):
                raise TypeError(
                    f'{class_path} is not a valid {expected_type.__name__}'
                )

            instance = adapter_class(config=config)
            cls._cache[cache_key] = instance
            return instance

        except ImportError as e:
            logger.error('Failed to import adapter %s: %s', class_path, e)
            raise
        except Exception as e:
            logger.error('Error loading adapter %s: %s', class_path, e)
            raise
