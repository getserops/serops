import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

// Every tab used to read "SerOps", so tabs, history and bookmarks were
// indistinguishable. The first matching rule names the page.
const RULES = [
  [/^\/login/, "login.welcomeBack"],
  [/^\/register/, "login.createAccount"],
  [/^\/dash\/?$/, "nav.dashboard"],
  [/^\/dash\/projects/, "nav.projects"],
  [/^\/dash\/data\/details\/([^/]+)/, "nav.data", 1],
  [/^\/dash\/data/, "nav.data"],
  [/^\/dash\/issues/, "nav.issues"],
  [/^\/dash\/investigate/, "nav.investigate"],
  [/^\/dash\/chat/, "nav.aiChat"],
  [/^\/dash\/traces/, "nav.traces"],
  [/^\/dash\/timeline\/([^/]+)/, "timeline.title", 1],
  [/^\/dash\/metrics\/([^/]+)/, "metrics.title", 1],
  [/^\/dash\/code-changes\/([^/]+)/, "codeChanges.title", 1],
  [/^\/dash\/profile/, "nav.profile"],
  [/^\/dash\/notifications/, "nav.notifications"],
  [/^\/dash\/settings\/team/, "settings.team.title"],
  [/^\/dash\/settings\/delivery/, "settings.delivery.title"],
  [/^\/dash\/settings\/routing-rules/, "settings.routing.title"],
  [/^\/dash\/settings\/ai/, "settings.ai.title"],
  [/^\/dash\/settings\/sentinel/, "sentinel.title"],
  [/^\/dash\/settings\/data/, "settings.data.title"],
  [/^\/dash\/settings\/integrations/, "globalIntegrations.title"],
  [/^\/dash\/settings\/traces/, "traces.settings.menuLabel"],
  [/^\/dash\/settings\/clusters/, "clusters.menuLabel"],
  [/^\/dash\/settings\/security/, "settings.security.title"],
  [/^\/dash\/settings\/audit/, "auditLog.title"],
  [/^\/dash\/settings/, "nav.settings"],
];

export function pageTitle(pathname, t) {
  for (const [pattern, key, group] of RULES) {
    const m = pathname.match(pattern);
    if (m) {
      const name = t(key);
      return group ? `${decodeURIComponent(m[group])} · ${name} · SerOps` : `${name} · SerOps`;
    }
  }
  return "SerOps";
}

export default function PageTitle() {
  const { pathname } = useLocation();
  const { t, i18n } = useTranslation();
  useEffect(() => {
    document.title = pageTitle(pathname, t);
  }, [pathname, t, i18n.language]);
  return null;
}
