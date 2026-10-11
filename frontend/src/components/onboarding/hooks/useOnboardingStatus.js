/**
 * Poll /api/organisation/onboarding/status/ and expose mutation helpers.
 *
 * Backend recomputes completion from real DB state on every GET, so a
 * short poll interval is how the wizard notices work the user did in
 * another tab / via the API / via the batch-dispatch signal.
 *
 * Poll cadence:
 *   - 5s while the tab is focused (aligns with research: 5-10s is the
 *     UX-standard for auto-detect wizards a la Sentry / Datadog).
 *   - 15s while the tab is hidden (backoff — user's not looking).
 *   - One-off refresh on `focus` (catches state that changed while the
 *     tab was in the background).
 *   - Backoff to 30s after 3 consecutive failures so a wonky backend
 *     doesn't get hammered from every open wizard.
 *
 * Never persist status or mutation payloads to localStorage — those
 * are session-scoped and can contain scratchpad hints about what the
 * user is configuring (e.g. selected_provider).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import apiClient from '../../../services/api-client';

const STATUS_URL = '/organisation/onboarding/status/';
const SKIP_URL = '/organisation/onboarding/skip/';
const RESUME_URL = '/organisation/onboarding/resume/';

const POLL_MS_FOCUSED = 5000;
const POLL_MS_HIDDEN = 15000;
const POLL_MS_BACKOFF = 30000;
const BACKOFF_AFTER_FAILURES = 3;

export function useOnboardingStatus({ enabled = true } = {}) {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Refs so the polling loop reads latest values without re-registering.
    const failureCountRef = useRef(0);
    const timeoutIdRef = useRef(null);
    const mountedRef = useRef(true);

    const clearTimer = useCallback(() => {
        if (timeoutIdRef.current !== null) {
            clearTimeout(timeoutIdRef.current);
            timeoutIdRef.current = null;
        }
    }, []);

    const fetchStatus = useCallback(async () => {
        try {
            const response = await apiClient.get(STATUS_URL);
            if (!mountedRef.current) return response.data;
            setStatus(response.data);
            setError(null);
            failureCountRef.current = 0;
            return response.data;
        } catch (err) {
            if (!mountedRef.current) return null;
            // 401 is handled by the apiClient interceptor (redirects to login).
            // We only surface other errors — network, 5xx, etc.
            if (err?.response?.status !== 401) {
                failureCountRef.current += 1;
                setError('Failed to load onboarding status');
            }
            return null;
        } finally {
            if (mountedRef.current) setLoading(false);
        }
    }, []);

    const scheduleNext = useCallback(() => {
        if (!enabled || !mountedRef.current) return;
        clearTimer();

        let delay = document.hidden ? POLL_MS_HIDDEN : POLL_MS_FOCUSED;
        if (failureCountRef.current >= BACKOFF_AFTER_FAILURES) {
            delay = POLL_MS_BACKOFF;
        }

        timeoutIdRef.current = setTimeout(async () => {
            await fetchStatus();
            scheduleNext();
        }, delay);
    }, [enabled, fetchStatus, clearTimer]);

    // Initial load + polling loop.
    useEffect(() => {
        mountedRef.current = true;
        if (!enabled) {
            setLoading(false);
            return () => {
                mountedRef.current = false;
                clearTimer();
            };
        }

        // Kick off an immediate fetch, then schedule the loop.
        fetchStatus().then(() => scheduleNext());

        // Refresh promptly when the user returns to the tab.
        const handleVisibilityChange = () => {
            if (!document.hidden) {
                fetchStatus();
                scheduleNext();
            }
        };
        const handleFocus = () => {
            fetchStatus();
            scheduleNext();
        };
        document.addEventListener('visibilitychange', handleVisibilityChange);
        window.addEventListener('focus', handleFocus);

        return () => {
            mountedRef.current = false;
            clearTimer();
            document.removeEventListener('visibilitychange', handleVisibilityChange);
            window.removeEventListener('focus', handleFocus);
        };
    }, [enabled, fetchStatus, scheduleNext, clearTimer]);

    // Manual mutation helpers — all return the updated status so the
    // caller can react without waiting for the next poll tick.

    const refresh = useCallback(async () => {
        return await fetchStatus();
    }, [fetchStatus]);

    const skipStep = useCallback(async (step) => {
        const response = await apiClient.put(STATUS_URL, {
            action: 'skip_step',
            step,
        });
        if (mountedRef.current) {
            setStatus(response.data);
            setError(null);
        }
        return response.data;
    }, []);

    const storeData = useCallback(async (data) => {
        const response = await apiClient.put(STATUS_URL, {
            action: 'store_data',
            data,
        });
        if (mountedRef.current) {
            setStatus(response.data);
            setError(null);
        }
        return response.data;
    }, []);

    const dismiss = useCallback(async () => {
        await apiClient.post(SKIP_URL);
        // Dismiss hides the wizard — refresh so is_skipped flips true.
        return await fetchStatus();
    }, [fetchStatus]);

    const resume = useCallback(async () => {
        await apiClient.post(RESUME_URL);
        return await fetchStatus();
    }, [fetchStatus]);

    return {
        status,
        loading,
        error,
        refresh,
        skipStep,
        storeData,
        dismiss,
        resume,
    };
}
