import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DemoBanner from '../DemoBanner';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

// The real English strings, so the test reads the sentence a visitor reads.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key.split('.').reduce((o, k) => o?.[k], en) ?? key }),
}));

const signIn = (user) => window.localStorage.getItem.mockImplementation(
  (k) => (k === 'user' ? JSON.stringify(user) : null),
);

describe('DemoBanner', () => {
  beforeEach(() => { window.localStorage.getItem.mockReset(); window.sessionStorage.clear(); });

  it('tells a demo user what the demo shows and links to the benchmark page', () => {
    signIn({ username: 'demo', is_demo: true });
    render(<DemoBanner />);
    expect(screen.getByRole('status').textContent).toContain(
      'Example data: analyses SerOps got right, from our own test environments. The misses are on the benchmark page.',
    );
    const link = screen.getByRole('link', { name: 'benchmark page' });
    expect(link).toHaveAttribute('href', 'https://serops.ai/benchmark');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.getByRole('link', { name: 'Self-host SerOps →' })).toBeInTheDocument();
  });

  it('shows nothing to any other user', () => {
    signIn({ username: 'alice', is_demo: false });
    const { container } = render(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows nothing when nobody is signed in', () => {
    const { container } = render(<DemoBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it('has its sentence in French', () => {
    for (const part of ['before', 'link', 'selfHost']) {
      expect(fr.demo.banner[part]).toBeTruthy();
      expect(fr.demo.banner[part]).not.toBe(en.demo.banner[part]);
    }
    const { before, link, after } = fr.demo.banner;
    expect(before + link + after).toBe(
      "Données d'exemple : des analyses que SerOps a réussies, issues de nos propres environnements de test. Les échecs sont sur la page du benchmark."
    );
  });

  it('publishes its height for layouts that fill the screen, and 0px when it is not shown', () => {
    signIn({ username: 'demo', is_demo: true });
    const { unmount } = render(<DemoBanner />);
    expect(document.documentElement.style.getPropertyValue('--demo-banner-h')).toMatch(/^\d+px$/);
    unmount();
    expect(document.documentElement.style.getPropertyValue('--demo-banner-h')).toBe('0px');
  });

  it('can be closed for the session and stays closed on the next page', () => {
    signIn({ username: 'demo', is_demo: true });
    const first = render(<DemoBanner />);
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(first.container).toBeEmptyDOMElement();
    expect(document.documentElement.style.getPropertyValue('--demo-banner-h')).toBe('0px');
    first.unmount();
    const second = render(<DemoBanner />);
    expect(second.container).toBeEmptyDOMElement();
  });
});

// A2: on a phone the banner took 104 px. It is one line there, the rest
// behind "More" (the stylesheet shows the button on a phone only).
describe('DemoBanner on a phone', () => {
  beforeEach(() => { window.localStorage.getItem.mockReset(); window.sessionStorage.clear(); });

  it('has a "More" control that opens and closes the full text', () => {
    signIn({ username: 'demo', is_demo: true });
    render(<DemoBanner />);
    const banner = screen.getByRole('status');
    const more = screen.getByRole('button', { name: 'More' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    expect(banner.className).not.toContain('is-expanded');
    fireEvent.click(more);
    expect(banner.className).toContain('is-expanded');
    expect(screen.getByRole('button', { name: 'Less' }).getAttribute('aria-expanded')).toBe('true');
  });

  it('keeps the close button', () => {
    signIn({ username: 'demo', is_demo: true });
    render(<DemoBanner />);
    expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
  });
});
