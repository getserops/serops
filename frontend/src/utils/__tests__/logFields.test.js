import { describe, it, expect } from 'vitest';
import { projectOf, serviceOf } from '../logFields';

describe('stored log fields', () => {
  it('reads the service whichever field carries it', () => {
    expect(serviceOf({ service_name: 'checkout' })).toBe('checkout');
    expect(serviceOf({ service: 'payments' })).toBe('payments');
    expect(serviceOf({ service: { name: 'checkout-api' } })).toBe('checkout-api');
    expect(serviceOf({})).toBeNull();
  });

  it('reads the project from project_name or project', () => {
    expect(projectOf({ project_name: 'shop' })).toBe('shop');
    expect(projectOf({ project: 'shop' })).toBe('shop');
    expect(projectOf({})).toBeNull();
  });
});
