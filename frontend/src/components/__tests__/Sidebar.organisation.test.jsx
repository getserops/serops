import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
vi.mock('../../services/api-client', () => ({ default: { get: () => new Promise(() => {}) } }));

import Sidebar from '../Sidebar';

describe('Sidebar organisation badge', () => {
  let store;
  beforeEach(() => {
    store = {};
    vi.stubGlobal('localStorage', {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('does not crash when the stored organisation is an id (saved profile)', () => {
    store.user = JSON.stringify({ role: 'admin', organisation: 1, permissions: [] });
    render(<MemoryRouter><Sidebar isOpen setIsOpen={() => {}} /></MemoryRouter>);
    expect(screen.getAllByRole('navigation').length).toBeGreaterThan(0);
  });

  it('shows the organisation name and its initial', () => {
    store.user = JSON.stringify({ role: 'admin', organisation: 'Acme', permissions: [] });
    render(<MemoryRouter><Sidebar isOpen setIsOpen={() => {}} /></MemoryRouter>);
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('A')).toBeInTheDocument();
  });
});
