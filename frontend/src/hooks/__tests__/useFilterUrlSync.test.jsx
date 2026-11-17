/**
 * The environment and cluster filter lives in the URL on the Overview,
 * Issues and Analyses pages: read on load, written on change.
 */
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { DeploymentProvider, useDeployment } from '../../context/DeploymentContext';
import useFilterUrlSync from '../useFilterUrlSync';

vi.mock('../../services/cluster.service', () => ({
  default: { list: vi.fn(() => Promise.resolve([{ id: 3, name: 'prod-eks' }, { id: 4, name: 'gke' }])) },
}));

const store = {};
Object.defineProperty(window, 'localStorage', {
  writable: true,
  value: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
  },
});

const setup = (url) => {
  const wrapper = ({ children }) => (
    <MemoryRouter initialEntries={[url]}><DeploymentProvider>{children}</DeploymentProvider></MemoryRouter>
  );
  return renderHook(() => {
    useFilterUrlSync();
    return { deployment: useDeployment(), location: useLocation() };
  }, { wrapper });
};

const query = (result) => new URLSearchParams(result.current.location.search);

describe('useFilterUrlSync', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem('token', 't');
  });

  it('applies the environment and cluster named in the URL', async () => {
    window.localStorage.setItem('serops.deployment.filter', JSON.stringify({ environment: 'production' }));
    const { result } = setup('/dash/issues?status=OPEN&environment=staging&cluster=3');
    await waitFor(() => expect(result.current.deployment.loading).toBe(false));
    expect(result.current.deployment.filter.environment).toBe('staging');
    expect(result.current.deployment.filter.clusterId).toBe(3);
    // The link's own values stay, and so do the other parameters.
    expect(query(result).get('environment')).toBe('staging');
    expect(query(result).get('status')).toBe('OPEN');
  });

  it('writes the persisted filter into a URL that has none', async () => {
    window.localStorage.setItem('serops.deployment.filter', JSON.stringify({ environment: 'development', clusterId: 4 }));
    const { result } = setup('/dash?tab=x');
    await waitFor(() => expect(query(result).get('environment')).toBe('development'));
    expect(query(result).get('cluster')).toBe('4');
    expect(query(result).get('tab')).toBe('x');
  });

  it('follows the picker', async () => {
    const { result } = setup('/dash/data');
    await waitFor(() => expect(result.current.deployment.loading).toBe(false));
    act(() => result.current.deployment.setFilter({ environment: 'staging', clusterId: 3 }));
    await waitFor(() => expect(query(result).get('environment')).toBe('staging'));
    expect(query(result).get('cluster')).toBe('3');
    act(() => result.current.deployment.setFilter({ environment: '', clusterId: null }));
    await waitFor(() => expect(query(result).get('environment')).toBeNull());
    expect(query(result).get('cluster')).toBeNull();
  });

  it('drops a cluster that does not exist', async () => {
    const { result } = setup('/dash?cluster=99');
    await waitFor(() => expect(result.current.deployment.loading).toBe(false));
    await waitFor(() => expect(query(result).get('cluster')).toBeNull());
    expect(result.current.deployment.filter.clusterId).toBeNull();
  });
});
