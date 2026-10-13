/**
 * DeploymentContext — composed filter state across the four deployment
 * dimensions: cluster, environment, region, namespace (Batch 54).
 *
 * Replaces the single-cluster ClusterContext with a filter object the
 * user can compose across dimensions ("show me the eu-west-1 production
 * slice of prod-eks in the payments namespace"). Each dimension is
 * independently nullable — null / '' means "no filter applied".
 *
 * Persisted to localStorage as ONE JSON blob so cross-tab sync happens
 * automatically. Backwards-compatible with the old
 * ``serops.cluster.selected`` integer key — reads that on first mount
 * if the new blob is missing, then migrates.
 *
 * Consumers use ``useDeployment()``. Legacy ``useCluster()`` is kept as
 * a thin alias so existing callsites don't need rewriting.
 *
 * Security: only stores IDs + short strings. No secrets, no PII.
 */

import React, { createContext, useContext, useEffect, useMemo, useState, useCallback } from 'react';
import { useLocation } from 'react-router-dom';
import ClusterService from '../services/cluster.service';

const STORAGE_KEY = 'serops.deployment.filter';
const LEGACY_CLUSTER_KEY = 'serops.cluster.selected';

const DEFAULT_FILTER = {
    clusterId: null,     // int | null — null = any cluster
    environment: '',     // string     — '' = any env
    region: '',
    namespace: '',
    deploymentId: null,  // int | null — pin to a specific ProjectDeployment
};

const DeploymentContext = createContext(null);

const readInitial = () => {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const parsed = JSON.parse(raw);
            // Merge with defaults so a partial persisted shape doesn't
            // leak undefined keys into the app.
            return { ...DEFAULT_FILTER, ...parsed };
        }
        // Legacy migration — the pre-Batch-54 ClusterContext stored
        // only the cluster ID under a different key. If present, seed
        // the new blob with it so the user's previous selection sticks.
        const legacyRaw = localStorage.getItem(LEGACY_CLUSTER_KEY);
        if (legacyRaw && legacyRaw !== 'null') {
            const n = parseInt(legacyRaw, 10);
            if (Number.isFinite(n) && n > 0) {
                return { ...DEFAULT_FILTER, clusterId: n };
            }
        }
    } catch {
        // localStorage may be blocked / JSON malformed — fall through
        // to defaults. Never crash the app over a persisted-filter read.
    }
    return { ...DEFAULT_FILTER };
};

const persist = (filter) => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(filter));
        // Keep the legacy key roughly in sync so any old code path
        // that still reads it (external scripts, embedded contexts)
        // doesn't diverge. Removed once we drop the legacy shim.
        if (filter.clusterId != null) {
            localStorage.setItem(LEGACY_CLUSTER_KEY, String(filter.clusterId));
        } else {
            localStorage.removeItem(LEGACY_CLUSTER_KEY);
        }
    } catch {
        // Silent — localStorage may be blocked in some sandboxes.
    }
};

const activeCountOf = (filter) => {
    let n = 0;
    if (filter.clusterId != null) n += 1;
    if (filter.environment) n += 1;
    if (filter.region) n += 1;
    if (filter.namespace) n += 1;
    if (filter.deploymentId != null) n += 1;
    return n;
};

export const DeploymentProvider = ({ children }) => {
    const [clusters, setClusters] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilterState] = useState(() => readInitial());

    // The provider wraps the login page too, so a load at mount runs
    // before there is a token and 401s. Re-read the token on every
    // navigation and load the clusters whenever it changes.
    useLocation();
    let token = null;
    try { token = localStorage.getItem('token'); } catch { /* storage blocked */ }

    // Load clusters so pickers can show names + the invalid-cluster
    // guard below can prune a stale ID.
    useEffect(() => {
        let cancelled = false;
        if (!token) {
            setClusters([]);
            setLoading(false);
            return undefined;
        }
        (async () => {
            try {
                setLoading(true);
                const rows = await ClusterService.list();
                if (!cancelled) setClusters(rows);
            } catch {
                if (!cancelled) setClusters([]);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [token]);

    // If the persisted clusterId points at a cluster that no longer
    // exists (deleted elsewhere), fall back to "any". Otherwise the
    // filter silently narrows everything to zero.
    useEffect(() => {
        if (!loading && filter.clusterId != null && !clusters.some((c) => c.id === filter.clusterId)) {
            setFilterState((prev) => {
                const next = { ...prev, clusterId: null, namespace: '' };
                persist(next);
                return next;
            });
        }
    }, [loading, clusters, filter.clusterId]);

    // Namespace requires cluster — same invariant as the model.
    // If the user clears the cluster the namespace has to go too.
    const setFilter = useCallback((partial) => {
        setFilterState((prev) => {
            const next = { ...prev, ...partial };
            if ('clusterId' in partial && partial.clusterId == null) {
                next.namespace = '';
            }
            persist(next);
            return next;
        });
    }, []);

    const setField = useCallback((field, value) => {
        setFilter({ [field]: value });
    }, [setFilter]);

    const resetFilters = useCallback(() => {
        setFilterState(() => {
            const next = { ...DEFAULT_FILTER };
            persist(next);
            return next;
        });
    }, []);

    // Cluster-picker convenience — same signature the old
    // useCluster.setClusterId hook had. Keeps the migration mechanical.
    const setClusterId = useCallback((id) => {
        setFilter({ clusterId: id ?? null });
    }, [setFilter]);

    const value = useMemo(() => {
        const currentCluster = clusters.find((c) => c.id === filter.clusterId) || null;
        return {
            // Composed filter object (canonical shape API layer reads)
            filter,
            setFilter,
            setField,
            resetFilters,
            activeCount: activeCountOf(filter),
            isFiltered: activeCountOf(filter) > 0,

            // Individual field exposure — reduces churn at callsites
            // (a component wanting just the env doesn't need to pluck).
            clusterId: filter.clusterId,
            environment: filter.environment,
            region: filter.region,
            namespace: filter.namespace,
            deploymentId: filter.deploymentId,

            // Cluster metadata + legacy helpers (kept for backwards compat)
            clusters,
            loading,
            currentCluster,
            setClusterId,
            hasMultiple: clusters.length >= 2,
        };
    }, [clusters, loading, filter, setFilter, setField, resetFilters, setClusterId]);

    return <DeploymentContext.Provider value={value}>{children}</DeploymentContext.Provider>;
};

export function useDeployment() {
    const ctx = useContext(DeploymentContext);
    if (ctx === null) {
        return {
            filter: { ...DEFAULT_FILTER },
            setFilter: () => {},
            setField: () => {},
            resetFilters: () => {},
            activeCount: 0, isFiltered: false,
            clusterId: null, environment: '', region: '', namespace: '', deploymentId: null,
            clusters: [], loading: false, currentCluster: null,
            setClusterId: () => {}, hasMultiple: false,
        };
    }
    return ctx;
}

/**
 * useCluster — kept as a thin alias for backwards compatibility.
 * New code should call useDeployment() directly.
 */
export function useCluster() {
    return useDeployment();
}

export default DeploymentContext;
