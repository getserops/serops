/**
 * ClusterContext — backwards-compat shim (Batch 54).
 *
 * The single-cluster context grew into DeploymentContext with composed
 * filters. This module re-exports the new provider + hook under the
 * old names so existing imports keep working without a mechanical
 * rewrite across the codebase. New code should import from
 * ``context/DeploymentContext`` directly.
 */

export {
    DeploymentProvider as ClusterProvider,
    useDeployment as useCluster,
    useDeployment,
    DeploymentProvider,
} from './DeploymentContext';

export { default } from './DeploymentContext';
