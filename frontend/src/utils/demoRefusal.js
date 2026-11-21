// What a refused write on the read-only demo looks like, and what to say.
// Kept apart from readOnlyDemo.js (which installs the HTTP interceptors) so
// that a service or a page can use it without loading the HTTP client or
// the translation setup: i18next is the instance that src/i18n.js initialises.
import i18next from "i18next";

const NOTICE_EN =
  "This is the read-only live demo, so changes aren't saved. Self-host SerOps to use your own data.";

export function isDemoRefusal(error) {
  return error?.response?.status === 403 && error.response.data?.error === "demo_read_only";
}

// For the places that show the failure themselves (a line in a form, a
// returned {error}): the sentence of the notice instead of the raw code
// "demo_read_only".
export function demoNoticeOr(error, text) {
  return isDemoRefusal(error) ? (i18next.isInitialized && i18next.t("demo.readOnlyNotice")) || NOTICE_EN : text;
}
