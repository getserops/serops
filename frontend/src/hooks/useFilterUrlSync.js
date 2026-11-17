import { useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDeployment } from '../context/DeploymentContext';

const parseCluster = (raw) => {
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
};

/**
 * Keep the global environment and cluster filter in the page's URL
 * (``?environment=staging&cluster=3``), so a link or a bookmark opens
 * the same slice.
 *
 * - A URL that carries any filter parameter decides alone: a shared
 *   link, a bookmark, back / forward. A parameter it leaves out means
 *   "all", never the stored choice (``?environment=staging`` shows
 *   staging on every cluster).
 * - A URL with no filter parameter takes the stored choice, which is
 *   then written into it (replace, so the picker doesn't fill the
 *   history).
 *
 * Other query parameters are left alone. A page that rewrites its whole
 * query string must carry ``environment`` and ``cluster`` over.
 */
export default function useFilterUrlSync(enabled = true) {
  const { filter, setFilter } = useDeployment();
  const [searchParams, setSearchParams] = useSearchParams();
  const urlEnv = searchParams.get('environment');
  const urlCluster = searchParams.get('cluster');
  const env = filter.environment || '';
  const clusterId = filter.clusterId ?? null;
  const cluster = clusterId != null ? String(clusterId) : '';
  const seenUrl = useRef(undefined);

  useEffect(() => {
    if (!enabled) {
      seenUrl.current = undefined;
      return;
    }
    const urlKey = `${urlEnv ?? ''}|${urlCluster ?? ''}`;
    const urlChanged = urlKey !== seenUrl.current;
    seenUrl.current = urlKey;
    if (urlKey === `${env}|${cluster}`) return;

    if (urlChanged && (urlEnv !== null || urlCluster !== null)) {
      const partial = {};
      const nextEnv = urlEnv === null || urlEnv === 'all' ? '' : urlEnv;
      if (nextEnv !== env) partial.environment = nextEnv;
      const nextCluster = urlCluster === null ? null : parseCluster(urlCluster);
      if (nextCluster !== clusterId) partial.clusterId = nextCluster;
      if (Object.keys(partial).length) {
        setFilter(partial);
        return;
      }
      // Nothing to apply ("all", a bad id): fall through and tidy the URL.
    }

    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (env) next.set('environment', env); else next.delete('environment');
      if (cluster) next.set('cluster', cluster); else next.delete('cluster');
      return next;
    }, { replace: true });
  }, [enabled, urlEnv, urlCluster, env, cluster, clusterId, setFilter, setSearchParams]);
}
