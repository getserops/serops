/**
 * Whether the signed-in user is the public read-only demo identity.
 *
 * Read from the login payload in localStorage rather than fetched on every
 * render. The flag is presentational only: the backend rejects every write
 * a demo user makes, whatever the UI shows.
 */
export function isDemoUser() {
  try {
    return Boolean(JSON.parse(localStorage.getItem('user') || '{}').is_demo);
  } catch {
    return false;
  }
}
