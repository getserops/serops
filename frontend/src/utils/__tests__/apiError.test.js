import { describe, it, expect } from 'vitest';
import { describeRequestError, NETWORK_ERROR, SERVER_ERROR } from '../apiError';

// The login form used to fall back to "Invalid credentials" for ANY axios
// failure, so a CORS block, an unreachable backend and a genuinely wrong
// password all read the same. Observed on a Helm install whose chart never set
// CORS_ALLOWED_ORIGINS: the preflight returned no Access-Control-Allow-Origin,
// the browser discarded the response, and the page blamed the password.

const REJECTED = 'Invalid credentials. Please try again.';

describe('describeRequestError', () => {
  it('does not blame credentials when no response arrived', () => {
    // axios shape for a network/CORS failure: request made, no response.
    const err = { request: {}, message: 'Network Error', code: 'ERR_NETWORK' };
    expect(describeRequestError(err, REJECTED)).toBe(NETWORK_ERROR);
  });

  it('mentions CORS, because that is the failure the user cannot see', () => {
    expect(describeRequestError({}, REJECTED).toLowerCase()).toContain('cors');
  });

  it('uses the rejection message when the server actually refused', () => {
    const err = { response: { status: 401, data: {} } };
    expect(describeRequestError(err, REJECTED)).toBe(REJECTED);
  });

  it("prefers the server's own error text", () => {
    const err = { response: { status: 400, data: { error: 'Account locked' } } };
    expect(describeRequestError(err, REJECTED)).toBe('Account locked');
  });

  it("falls back to the server's message field", () => {
    const err = { response: { status: 400, data: { message: 'Too many attempts' } } };
    expect(describeRequestError(err, REJECTED)).toBe('Too many attempts');
  });

  it('reports a 5xx as a server error, not a credentials problem', () => {
    const err = { response: { status: 503, data: {} } };
    expect(describeRequestError(err, REJECTED)).toBe(SERVER_ERROR);
  });

  it('handles a null error without throwing', () => {
    expect(describeRequestError(null, REJECTED)).toBe(NETWORK_ERROR);
  });
});
