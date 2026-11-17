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
 * - The URL wins when it changes and names a value: a shared link, a
 *   bookmark, back / forward.
 * - Otherwise the filter wins and is written into the URL (replace, so
 *   the picker doesn't fill the history).
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
      const nextEnv = urlEnv === 'all' ? '' : urlEnv;
      if (urlEnv !== null && nextEnv !== env) partial.environment = nextEnv;
      const nextCluster = urlCluster === null ? null : parseCluster(urlCluster);
      if (urlCluster !== null && nextCluster !== clusterId) partial.clusterId = nextCluster;
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
