import React, { useState } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
vi.mock('../../services/api-client', () => ({ default: { get: () => new Promise(() => {}) } }));
// A phone: the menu is a drawer.
vi.mock('@mui/material', () => ({ useMediaQuery: () => true }));

import Sidebar from '../Sidebar';

// A10: on a phone the drawer opened with the focus left on the page behind,
// Escape did nothing and the page scrolled under it.
const Page = () => {
  const [open, setOpen] = useState(false);
  return (
    <MemoryRouter initialEntries={['/dash/issues']}>
      <button type="button" onClick={() => setOpen(true)}>open menu</button>
      <Sidebar isOpen={open} setIsOpen={setOpen} />
    </MemoryRouter>
  );
};

describe('Sidebar as a drawer on a phone', () => {
  let store;
  beforeEach(() => {
    store = { user: JSON.stringify({ role: 'admin', organisation: 'Acme', permissions: [] }) };
    vi.stubGlobal('localStorage', {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    });
  });
  afterEach(() => { vi.unstubAllGlobals(); document.body.style.overflow = ''; });

  const openDrawer = () => {
    const opener = screen.getByText('open menu');
    opener.focus();
    fireEvent.click(opener);
    return opener;
  };

  it('is out of the Tab order while closed', () => {
    render(<Page />);
    expect(screen.getByRole('navigation', { hidden: true }).hasAttribute('inert')).toBe(true);
  });

  it('moves the focus to the current page of the menu when it opens', () => {
    render(<Page />);
    openDrawer();
    const nav = screen.getByRole('navigation');
    expect(nav.hasAttribute('inert')).toBe(false);
    expect(nav.contains(document.activeElement)).toBe(true);
    expect(document.activeElement.getAttribute('aria-current')).toBe('page');
  });

  it('closes on Escape and gives the focus back to the button that opened it', () => {
    render(<Page />);
    const opener = openDrawer();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.getByRole('navigation', { hidden: true }).className).not.toContain('is-open');
    expect(document.activeElement).toBe(opener);
  });

  it('stops the page behind from scrolling while it is open', () => {
    render(<Page />);
    openDrawer();
    expect(document.body.style.overflow).toBe('hidden');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(document.body.style.overflow).toBe('');
  });

  it('keeps Tab inside the drawer', () => {
    render(<Page />);
    openDrawer();
    const backdrop = document.querySelector('.app-sidebar-backdrop');
    backdrop.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(screen.getByRole('navigation').contains(document.activeElement)).toBe(true);
  });
});
