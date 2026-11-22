// Live demo: props that switch a write control off and say why.
//
//   const lock = useDemoLock();
//   <button onClick={save} {...lock}>Save</button>
//
// For the demo user the control is disabled and its tooltip carries the
// common read-only sentence; for everyone else the object is empty and the
// control is untouched. Spread it AFTER the control's own props so that it
// wins over a `disabled={...}` or `title` already there. Settings pages lock
// a whole subtree instead (demoReadOnlyControls.js); the 403 handler in
// readOnlyDemo.js stays as the backstop for anything missed.
import { useTranslation } from "react-i18next";
import { isDemoUser } from "./demo";

const NONE = Object.freeze({});

export const demoLockProps = (t) =>
  isDemoUser() ? { disabled: true, "aria-disabled": true, title: t("demo.readOnlyNotice") } : NONE;

export const useDemoLock = () => {
  const { t } = useTranslation();
  return demoLockProps(t);
};

export default useDemoLock;
