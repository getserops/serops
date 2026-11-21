// Page counts for an operator's public demo instance. Off by default: the
// app asks /api/client-config/ once, and unless the operator configured
// usage counting it loads nothing and sends nothing.
//
// When on, only this leaves the browser: the *name* of the page shown
// (/dash/data/details/:id, never the id), a few event names, the browser's
// language and screen size, and the site a first visit came from. No record
// id, no query string, no search or chat text. Do Not Track is respected.

const BASE_URL = import.meta.env.VITE_BASE_URL;

// Every fixed word a route can contain. Anything else in a path is a record
// id, a token or a name, and is sent as ":id".
const STATIC_SEGMENTS = new Set([
  'dash', 'login', 'register', 'register_verif', 'accept_invitation', 'invitation_password', 'email', 'confirm',
  'password', 'reset', 'auth', 'callback', 'profile', 'data', 'details', 'metrics', 'code-changes', 'issues',
  'investigate', 'notifications', 'chat', 'traces', 'batch', 'timeline', 'projects', 'settings', 'team', 'teams',
  'delivery', 'routing-rules', 'preferences', 'ai', 'sentinel', 'security', 'audit', 'integrations', 'clusters',
]);

/** /dash/data/details/acme-batch-42?x=1 -> /dash/data/details/:id */
export function routeName(pathname) {
  const clean = String(pathname || '/').split('?')[0].split('#')[0];
  const parts = clean.split('/').filter(Boolean).map((p) => (STATIC_SEGMENTS.has(p) ? p : ':id'));
  return `/${parts.join('/')}`;
}

/** The event a page view also stands for, if any. */
export function pageEvent(route) {
  if (route === '/dash/data/details/:id') return 'analysis_opened';
  if (route === '/dash/chat') return 'chat_opened';
  return null;
}

/** Only the site a visit came from, and only when it is another site. */
export function externalReferrer(referrer, origin) {
  try {
    const url = new URL(referrer);
    return url.origin === origin ? '' : `${url.origin}/`;
  } catch {
    return '';
  }
}

let state = { started: false, ready: false, queue: [], firstView: true };

function send(payload) {
  if (!state.ready || !window.umami) {
    if (state.queue.length < 50) state.queue.push(payload);
    return;
  }
  try {
    // Replace what the tracker would read from the address bar and the title.
    window.umami.track((props) => ({ ...props, ...payload }));
  } catch { /* counting must never break the app */ }
}

export function trackPage(pathname) {
  if (!state.started) return;
  const route = routeName(pathname);
  const referrer = state.firstView ? externalReferrer(document.referrer, window.location.origin) : '';
  state.firstView = false;
  send({ url: route, title: route, referrer });
  const event = pageEvent(route);
  if (event) send({ url: route, title: route, referrer: '', name: event });
}

export function trackEvent(name) {
  if (!state.started) return;
  const route = routeName(window.location.pathname);
  send({ url: route, title: route, referrer: '', name });
}

/**
 * The event for a link that leaves the app: which kind of place it goes to,
 * never the address. GitHub and the documentation are named; anything else
 * is "outbound_click". Links inside the app are not events.
 */
export function outboundEvent(href, origin) {
  let url;
  try {
    url = new URL(href, origin);
  } catch {
    return null;
  }
  if (!/^https?:$/.test(url.protocol) || url.origin === origin) return null;
  if (url.hostname === 'github.com' || url.hostname.endsWith('.github.com')) return 'github_click';
  if (url.hostname === 'docs.serops.ai' || (url.hostname === 'serops.ai' && /^\/docs(\/|$)/.test(url.pathname))) return 'docs_click';
  return 'outbound_click';
}

function onOutboundClick(e) {
  const a = e.target?.closest?.('a[href]');
  if (!a) return;
  const name = outboundEvent(a.getAttribute('href'), window.location.origin);
  if (name) trackEvent(name);
}

/**
 * Ask the server whether usage counting is configured, and start it if so.
 * Returns true when counting is on. Safe to call more than once.
 */
export async function startUsageAnalytics(fetchImpl = window.fetch.bind(window)) {
  if (state.started) return true;
  let usage = null;
  try {
    const res = await fetchImpl(`${BASE_URL}/client-config/`, { credentials: 'omit' });
    usage = res.ok ? (await res.json()).usage : null;
  } catch {
    usage = null;
  }
  // Same checks as the server: a path on this origin, nothing else.
  if (!usage || !/^\/(?!\/)[A-Za-z0-9._/-]+\.js$/.test(usage.script_path || '') || !usage.website_id) return false;
  state.started = true;
  const script = document.createElement('script');
  script.defer = true;
  script.src = usage.script_path;
  script.setAttribute('data-website-id', usage.website_id);
  // The app reports pages itself (names only); the tracker reads no address.
  script.setAttribute('data-auto-track', 'false');
  script.setAttribute('data-do-not-track', 'true');
  script.setAttribute('data-exclude-search', 'true');
  script.setAttribute('data-exclude-hash', 'true');
  script.setAttribute('data-host-url', window.location.origin + usage.script_path.replace(/\/[^/]*$/, ''));
  script.onload = () => {
    state.ready = true;
    const queued = state.queue;
    state.queue = [];
    queued.forEach(send);
  };
  document.head.appendChild(script);
  document.addEventListener('click', onOutboundClick, true);
  return true;
}

/** For tests. */
export function _reset() {
  document.removeEventListener('click', onOutboundClick, true);
  state = { started: false, ready: false, queue: [], firstView: true };
}
