// The public demo is read-only: the backend refuses every write with
// 403 {"error": "demo_read_only"}. Pages handle failures their own way
// ("Error", "Rotation failed", a raw code...), so a visitor clicking Save
// saw a different, alarming message on every page.
//
// Here every refusal shows one friendly notice, and the page's own error
// toast that follows within the same moment is dropped, so the visitor reads
// one explanation instead of an error.
import axios from "axios";
import { toast } from "react-toastify";
import i18n from "../i18n";
import apiClient from "../services/api-client";

export const DEMO_TOAST_ID = "demo-read-only";
const FOLLOW_UP_MS = 2500;
let refusedAt = 0;

export function isDemoRefusal(error) {
  return error?.response?.status === 403 && error.response.data?.error === "demo_read_only";
}

function onError(error) {
  if (isDemoRefusal(error)) {
    refusedAt = Date.now();
    toast.info(i18n.t("demo.readOnlyNotice"), { toastId: DEMO_TOAST_ID });
  }
  return Promise.reject(error);
}

let installed = false;
export function installReadOnlyDemoHandling() {
  if (installed) return;
  installed = true;
  axios.interceptors.response.use((r) => r, onError);
  apiClient.interceptors.response.use((r) => r, onError);
  const showError = toast.error;
  toast.error = (content, options) =>
    Date.now() - refusedAt < FOLLOW_UP_MS ? undefined : showError(content, options);
}
