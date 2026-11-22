import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";

// Every tab used to read "SerOps", so tabs, history and bookmarks were
// indistinguishable. The first matching rule names the page.
const RULES = [
  [/^\/login/, "login.welcomeBack"],
  [/^\/register/, "login.createAccount"],
  [/^\/dash\/?$/, "nav.overview"],
  [/^\/dash\/projects/, "nav.projects"],
  [/^\/dash\/data\/details\/([^/]+)/, "nav.analyses", 1],
  [/^\/dash\/data/, "nav.analyses"],
  [/^\/dash\/issues/, "nav.issues"],
  [/^\/dash\/investigate/, "nav.investigate"],
  [/^\/dash\/chat/, "nav.aiChat"],
  [/^\/dash\/traces/, "nav.traces"],
  [/^\/dash\/timeline\/([^/]+)/, "timeline.title", 1],
  [/^\/dash\/metrics\/([^/]+)/, "metrics.title", 1],
  [/^\/dash\/code-changes\/([^/]+)/, "codeChanges.title", 1],
  [/^\/dash\/profile/, "nav.profile"],
  [/^\/dash\/notifications/, "nav.notifications"],
  [/^\/dash\/settings\/teams/, "teams.title"],
  [/^\/dash\/settings\/team/, "settings.team.title"],
  [/^\/dash\/settings\/roles/, "roles.title"],
  [/^\/dash\/settings\/delivery/, "nav.alertsRouting"],
  [/^\/dash\/settings\/routing-rules/, "nav.alertsRouting"],
  [/^\/dash\/settings\/ai/, "settings.ai.title"],
  [/^\/dash\/settings\/sentinel/, "sentinel.title"],
  [/^\/dash\/settings\/data/, "settings.data.title"],
  [/^\/dash\/settings\/integrations/, "globalIntegrations.title"],
  [/^\/dash\/settings\/traces/, "traces.settings.menuLabel"],
  [/^\/dash\/settings\/clusters/, "clusters.menuLabel"],
  [/^\/dash\/settings\/security/, "settings.security.title"],
  // Pages of the paid modules: their names are only loaded with src/ee/.
  [/^\/dash\/settings\/audit-streaming/, "ee.auditStream.menuLabel"],
  [/^\/dash\/settings\/license/, "ee.license.menuLabel"],
  [/^\/dash\/settings\/audit/, "auditLog.title"],
  [/^\/dash\/settings\/preferences/, "preferences.title"],
  [/^\/dash\/settings\/?$/, "settings.general.menuLabel"],
  [/^\/dash\/settings/, "nav.settings"],
];

export function pageTitle(pathname, t) {
  for (const [pattern, key, group] of RULES) {
    const m = pathname.match(pattern);
    if (m) {
      // A name that is not loaded (a paid page in the Community build)
      // falls back to "Settings", never to the raw key.
      let name = t(key);
      if (name === key && key.startsWith("ee.")) name = t("nav.settings");
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
