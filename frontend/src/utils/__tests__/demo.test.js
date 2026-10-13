import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isDemoUser } from '../demo';

describe('isDemoUser', () => {
  let store;

  beforeEach(() => {
    store = {};
    vi.stubGlobal('localStorage', {
      getItem: (key) => (key in store ? store[key] : null),
      setItem: (key, value) => { store[key] = String(value); },
    });
  });

  afterEach(() => vi.unstubAllGlobals());

  it('is true for the demo identity', () => {
    store.user = JSON.stringify({ username: 'demo', is_demo: true });
    expect(isDemoUser()).toBe(true);
  });

  it('is false for a regular user', () => {
    store.user = JSON.stringify({ username: 'alice', is_demo: false });
    expect(isDemoUser()).toBe(false);
  });

  it('is false when nobody is signed in', () => {
    expect(isDemoUser()).toBe(false);
  });

  it('is false when the stored payload is not JSON', () => {
    store.user = 'not-json';
    expect(isDemoUser()).toBe(false);
  });
});
