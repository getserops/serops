/**
 * Integrations run end to end on a managed Kubernetes cluster with a
 * released SerOps version. Same facts as the Maturity column of
 * docs/src/integrations/compatibility.md: change both together.
 */
const LIVE_TESTED = {
    cloudwatch: { platform: 'EKS 1.36', version: '1.3.0', date: '2026-11-13' },
    gcp: { platform: 'GKE 1.36', version: '1.3.0', date: '2026-11-12' },
    azure: { platform: 'AKS 1.36', version: '1.3.0', date: '2026-11-11' },
};

export function liveTested(providerCode) {
    return LIVE_TESTED[providerCode] || null;
}

/** "EKS 1.36, SerOps 1.3.0, 2026-11-13", or "". */
export function liveTestedDetail(providerCode) {
    const t = liveTested(providerCode);
    return t ? `${t.platform}, SerOps ${t.version}, ${t.date}` : '';
}

/** "Live-tested: EKS 1.36, SerOps 1.3.0, 2026-11-13", or "". */
export function liveTestedText(providerCode) {
    const detail = liveTestedDetail(providerCode);
    return detail ? `Live-tested: ${detail}` : '';
}
