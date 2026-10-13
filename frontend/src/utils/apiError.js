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
  const fromServer = response.data?.error || response.data?.message;
  if (fromServer) return fromServer;

  if (response.status >= 500) return SERVER_ERROR;

  return rejectedMsg;
}

export default describeRequestError;
