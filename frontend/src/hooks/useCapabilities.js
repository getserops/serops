/**
 * useCapabilities — resolves the caller org's enabled data-source
 * capabilities. Returns { capabilities, loading, error, has }.
 *
 * ``has(name)`` is the ergonomic check for JSX guards:
 *
 *     const { has } = useCapabilities();
 *     return has('traces') ? <TracesEntry /> : null;
 *
 * While loading, ``has()`` returns TRUE (permissive default) so we
 * don't flash "empty" UI on first paint. Once the API responds, only
 * enabled sources remain visible.
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import CapabilityService from '../services/capability.service';

export function useCapabilities() {
    const [capabilities, setCapabilities] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                const data = await CapabilityService.get();
                if (!cancelled) {
                    setCapabilities(Array.isArray(data?.capabilities) ? data.capabilities : []);
                }
            } catch (err) {
                if (!cancelled) setError(err);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, []);

    const has = useCallback((name) => {
        if (capabilities === null) return true;   // permissive during load
        return capabilities.includes(name);
    }, [capabilities]);

    return useMemo(
        () => ({ capabilities, loading, error, has }),
        [capabilities, loading, error, has],
    );
}

export default useCapabilities;
