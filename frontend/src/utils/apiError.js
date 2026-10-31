/**
 * Turn an axios failure into a message that says what actually went wrong.
 *
 * The login form used to fall back to "Invalid credentials" for ANY failure,
 * so a CORS block, an unreachable backend and a genuinely wrong password were
 * indistinguishable. That is an expensive lie: it sends the user to re-type a
 * password that was always correct while the real fault — a misconfigured
 * origin, a backend that is down — goes unmentioned.
 *
 * Observed on a Helm install: the chart never set CORS_ALLOWED_ORIGINS, the
 * preflight came back without an Access-Control-Allow-Origin header, the
 * browser discarded the response, and the page reported bad credentials.
 *
 * The distinction axios gives us is whether a response ever arrived:
 *   - no `response` at all  -> the request never completed (network, CORS, DNS,
 *     server down). Nothing can be said about the credentials.
 *   - a `response`          -> the server answered and its status is the truth.
 */

export const NETWORK_ERROR =
  "Could not reach the server. Check that the API is running and that your " +
  "browser is allowed to call it (CORS).";

export const SERVER_ERROR =
  "The server encountered an error. Try again shortly.";

export const RATE_LIMITED = "Too many attempts. Try again later.";

// DRF's throttle answer: "Request was throttled. Expected available in 3412 seconds."
function rateLimitMessage(detail) {
  const seconds = Number(String(detail || "").match(/available in (\d+) second/)?.[1]);
  if (!seconds) return RATE_LIMITED;
  const minutes = Math.ceil(seconds / 60);
  return `Too many attempts. Try again in ${minutes} minute${minutes === 1 ? "" : "s"}.`;
}

// First message of a DRF validation error ({"user": {"email": ["..."]}}).
function firstFieldError(data) {
  if (typeof data === "string") return data;
  if (Array.isArray(data)) {
    for (const item of data) {
      const found = firstFieldError(item);
      if (found) return found;
    }
    return null;
  }
  if (data && typeof data === "object") {
    for (const value of Object.values(data)) {
      const found = firstFieldError(value);
      if (found) return found;
    }
  }
  return null;
}

/**
 * @param {unknown} error        the rejection from axios
 * @param {string}  rejectedMsg  what to say when the server actively refused
 *                               the request (e.g. bad credentials)
 */
export function describeRequestError(error, rejectedMsg) {
  const response = error?.response;

  // No response: the request never made it back. Never attribute this to the
  // credentials — they were never checked.
  if (!response) {
    return NETWORK_ERROR;
  }

  // Prefer whatever the server said; it knows more than we do.
  // Some endpoints answer {error: "<code>", message: "<sentence>"} (the demo's
  // "demo_read_only"): the sentence is for people, the code for programs.
  const fromServer = response.data?.message || response.data?.error;
  if (fromServer) return fromServer;

  // Rate limits answer with `detail`, which used to be ignored: a throttled
  // sign-up said "Registration failed" and a throttled invitation password
  // "Wrong password" (journey suite, B7).
  if (response.status === 429) return rateLimitMessage(response.data?.detail);
  if (typeof response.data?.detail === "string") return response.data.detail;

  if (response.status >= 500) return SERVER_ERROR;

  if (response.status === 400) {
    const field = firstFieldError(response.data);
    if (field) return field;
  }

  return rejectedMsg;
}

export default describeRequestError;
