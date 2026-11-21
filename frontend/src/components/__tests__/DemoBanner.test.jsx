import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
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
  beforeEach(() => window.localStorage.getItem.mockReset());

  it('tells a demo user what the demo shows and links to the benchmark page', () => {
    signIn({ username: 'demo', is_demo: true });
    render(<DemoBanner />);
    expect(screen.getByRole('status').textContent).toContain(
      'These are analyses SerOps got right. The misses are on the benchmark page. '
      + 'They are selected from our benchmark runs on test environments we built, shown under the name Acme Cloud. '
      + 'SerOps found the cause in each incident shown here; two are healthy windows where it rightly raised nothing. '
      + 'Counts reflect the analyses shown here.',
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
    for (const part of ['before', 'link', 'after', 'selfHost']) {
      expect(fr.demo.banner[part]).toBeTruthy();
      expect(fr.demo.banner[part]).not.toBe(en.demo.banner[part]);
    }
  });
});
