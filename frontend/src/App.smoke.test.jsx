import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

// Replaces the Create-React-App boilerplate that used to live in
// src/App.test.js. That file asserted `getByText(/learn react/i)` — scaffolding
// text that has never appeared anywhere in SerOps, so it could not pass — and
// it was named `.js` while containing JSX, so vitest could not even parse it:
// the whole suite reported a failed FILE, not a failed assertion. It was noise
// that had to be read past on every run.
//
// This asserts something that can actually regress: that App's route table
// mounts and an unauthenticated visitor lands on the login route.

vi.mock('./services/api-client', () => ({
  default: {
    get: vi.fn().mockResolvedValue({ data: {} }),
    post: vi.fn().mockResolvedValue({ data: {} }),
    delete: vi.fn().mockResolvedValue({ data: {} }),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k) => k, i18n: { changeLanguage: vi.fn() } }),
  Trans: ({ children }) => children,
}));

describe('App', () => {
  it('mounts its route table without crashing', async () => {
    const { default: App } = await import('./App');
    expect(() => render(<App />)).not.toThrow();
  });

  it('sends an unauthenticated visitor to the login route', async () => {
    window.history.pushState({}, '', '/');
    const { default: App } = await import('./App');
    render(<App />);
    // Routes are lazy, so wait for the chunk to resolve rather than asserting
    // against the Suspense fallback.
    await waitFor(
      () => expect(window.location.pathname).toBe('/login'),
      { timeout: 5000 },
    );
  });

  it('exposes a default export that is a component', async () => {
    const mod = await import('./App');
    expect(typeof mod.default).toBe('function');
  });
});
