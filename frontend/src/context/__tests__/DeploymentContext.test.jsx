/**
 * Tests for DeploymentContext (Batch 54).
 *
 * Covers:
 *  - Default filter shape (all null / '')
 *  - Legacy migration from `serops.cluster.selected` on first mount
 *  - setField persists to localStorage
 *  - Namespace clears when clusterId cleared (invariant)
 *  - resetFilters clears everything + persists
 *  - useCluster alias returns the same shape as useDeployment
 */

import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { DeploymentProvider, useDeployment, useCluster } from '../DeploymentContext';

vi.mock('../../services/cluster.service', () => ({
    default: {
        list: vi.fn(() => Promise.resolve([
            { id: 1, name: 'prod-eks', provider_display: 'AWS EKS', is_active: true },
            { id: 2, name: 'staging-gke', provider_display: 'GCP GKE', is_active: true },
        ])),
    },
}));

const localStorageMock = (() => {
    let store = {};
    return {
        getItem: vi.fn((key) => store[key] || null),
        setItem: vi.fn((key, value) => { store[key] = String(value); }),
        removeItem: vi.fn((key) => { delete store[key]; }),
        clear: vi.fn(() => { store = {}; }),
        _dump: () => store,
    };
})();
Object.defineProperty(window, 'localStorage', {
    value: localStorageMock, writable: true,
});

const wrap = ({ children }) => <DeploymentProvider>{children}</DeploymentProvider>;

describe('DeploymentContext', () => {
    beforeEach(() => {
        localStorageMock.clear();
        vi.clearAllMocks();
    });

    it('defaults to an unfiltered shape', async () => {
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        expect(result.current.filter).toEqual({
            clusterId: null, environment: '', region: '', namespace: '', deploymentId: null,
        });
        expect(result.current.isFiltered).toBe(false);
        expect(result.current.activeCount).toBe(0);
    });

    it('migrates legacy cluster localStorage key on first mount', async () => {
        localStorageMock.setItem('serops.cluster.selected', '2');
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        expect(result.current.filter.clusterId).toBe(2);
        expect(result.current.activeCount).toBe(1);
    });

    it('setField persists to localStorage as one JSON blob', async () => {
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        act(() => { result.current.setField('environment', 'production'); });
        expect(result.current.filter.environment).toBe('production');

        const stored = JSON.parse(localStorageMock.getItem('serops.deployment.filter'));
        expect(stored.environment).toBe('production');
    });

    it('setField(cluster, id) also mirrors to the legacy key', async () => {
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        act(() => { result.current.setField('clusterId', 1); });
        expect(localStorageMock.getItem('serops.cluster.selected')).toBe('1');

        act(() => { result.current.setField('clusterId', null); });
        expect(localStorageMock.getItem('serops.cluster.selected')).toBe(null);
    });

    it('clearing clusterId also clears namespace (invariant)', async () => {
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        act(() => {
            result.current.setField('clusterId', 1);
            result.current.setField('namespace', 'payments');
        });
        expect(result.current.filter.namespace).toBe('payments');

        act(() => { result.current.setField('clusterId', null); });
        expect(result.current.filter.namespace).toBe('');
    });

    it('resetFilters clears every dimension + persists', async () => {
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        act(() => {
            result.current.setFilter({
                clusterId: 1, environment: 'production', region: 'us-east-1',
            });
        });
        expect(result.current.activeCount).toBe(3);

        act(() => { result.current.resetFilters(); });
        expect(result.current.activeCount).toBe(0);
        const stored = JSON.parse(localStorageMock.getItem('serops.deployment.filter'));
        expect(stored).toEqual({
            clusterId: null, environment: '', region: '', namespace: '', deploymentId: null,
        });
    });

    it('useCluster alias returns the same shape', async () => {
        const { result } = renderHook(() => useCluster(), { wrapper: wrap });
        await waitFor(() => expect(result.current.loading).toBe(false));

        expect(result.current).toHaveProperty('clusterId');
        expect(result.current).toHaveProperty('setClusterId');
        expect(result.current).toHaveProperty('hasMultiple');
        expect(result.current).toHaveProperty('filter');
    });

    it('prunes a stale clusterId when the referenced cluster is gone', async () => {
        localStorageMock.setItem('serops.deployment.filter', JSON.stringify({
            clusterId: 999, environment: '', region: '', namespace: '', deploymentId: null,
        }));
        const { result } = renderHook(() => useDeployment(), { wrapper: wrap });

        await waitFor(() => expect(result.current.loading).toBe(false));
        await waitFor(() => expect(result.current.filter.clusterId).toBe(null));
    });
});
