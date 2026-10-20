import React, { useEffect, useState } from "react";
import "./Sidebar.css";
import {
  LayoutDashboard,
  CircleAlert,
  Activity,
  Search,
  MessageSquare,
  Folder,
  Plug,
  Route,
  SlidersHorizontal,
  ChevronDown,
  ChevronRight,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import SerOpsMark from "./SerOpsMark";
import { useMediaQuery } from "@mui/material";
import { useTranslation } from "react-i18next";
import { refreshPermissions, usePermissions } from "../utils/permissions";

// Full-height app sidebar, grouped by what people come to do:
// Monitor (what's happening), Investigate (dig in), Configure (set up).
const Sidebar = ({ isOpen, setIsOpen }) => {
  const { t } = useTranslation();
  const can = usePermissions();
  const isSmallScreen = useMediaQuery("(max-width: 860px)");
  const location = useLocation();
  const path = location.pathname;
  const onSettings = path.startsWith("/dash/settings")
    && !path.startsWith("/dash/settings/integrations")
    && !path.startsWith("/dash/settings/delivery")
    && !path.startsWith("/dash/settings/routing-rules");
  const [settingsOpen, setSettingsOpen] = useState(onSettings);

  const user = JSON.parse(localStorage.getItem("user")) || {};
  const [organisation, setOrganisation] = useState(
    [user?.organisation_name, user?.organisation].find((v) => typeof v === 'string' && v) || null
  );

  const [orgLogo, setOrgLogo] = useState(null);

  // Pick up role changes made while signed in (and permissions for sessions
  // that began before the server sent them).
  useEffect(() => { refreshPermissions(); }, []);

  // Load the organisation's name and logo from the API: localStorage.user
  // can be stale or missing (token-only sessions, cookie refresh) and never
  // carries the logo. Settings → General announces changes with a
  // "serops:org-updated" event so the sidebar follows without a reload.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const apiClient = (await import('../services/api-client')).default;
        const res = await apiClient.get('/organisation/info/');
        if (cancelled) return;
        const name = res?.data?.name || res?.data?.organisation_name;
        if (name) {
          setOrganisation(name);
          try {
            const cur = JSON.parse(localStorage.getItem('user')) || {};
            localStorage.setItem('user', JSON.stringify({ ...cur, organisation: name }));
          } catch { /* localStorage may be blocked */ }
        }
        setOrgLogo(res?.data?.logo_url || null);
      } catch {
        /* keep what localStorage had rather than show a placeholder */
      }
    })();
    const onUpdate = (e) => {
      if (e.detail?.name) setOrganisation(e.detail.name);
      if ('logo_url' in (e.detail || {})) setOrgLogo(e.detail.logo_url || null);
    };
    window.addEventListener('serops:org-updated', onUpdate);
    return () => { cancelled = true; window.removeEventListener('serops:org-updated', onUpdate); };
  }, []);

  useEffect(() => {
    if (onSettings) setSettingsOpen(true);
  }, [onSettings]);

  useEffect(() => {
    setIsOpen(!isSmallScreen);
  }, [isSmallScreen]);

  const groups = [
    {
      id: "monitor",
      label: t("nav.groupMonitor"),
      items: [
        { path: "/dash", name: t("nav.overview"), icon: LayoutDashboard, exact: true },
        { path: "/dash/issues", name: t("nav.issues"), icon: CircleAlert },
        { path: "/dash/data", name: t("nav.analyses"), icon: Activity },
      ],
    },
    {
      id: "investigate",
      label: t("nav.groupInvestigate"),
      items: [
        { path: "/dash/investigate", name: t("nav.investigate"), icon: Search },
        { path: "/dash/chat", name: t("nav.aiChat"), icon: MessageSquare },
      ],
    },
    {
      id: "configure",
      label: t("nav.groupConfigure"),
      items: [
        { path: "/dash/projects", name: t("nav.projects"), icon: Folder },
        { path: "/dash/settings/integrations", name: t("nav.integrations"), icon: Plug },
        {
          path: "/dash/settings/delivery",
          name: t("nav.alertsRouting"),
          icon: Route,
          match: ["/dash/settings/delivery", "/dash/settings/routing-rules"],
        },
      ],
    },
  ];

  // The sidebar lists tasks, not data sources: traces (like logs and
  // metrics) are reached from an analysis, from Settings → Distributed
  // Traces ("View received traces") and from ⌘K.
  // Each page is listed for the users who can open it (the permission its
  // API needs, from the server's list: see utils/permissions).
  const settingsItems = [
    { path: "/dash/settings", name: t("settings.general.menuLabel"), exact: true },
    { path: "/dash/settings/team", name: t("settings.team.title"), perm: "team.manage" },
    { path: "/dash/settings/ai", name: t("settings.ai.title"), perm: "settings.manage" },
    { path: "/dash/settings/sentinel", name: "Sentinel", perm: "settings.manage" },
    { path: "/dash/settings/data", name: t("settings.data.title"), perm: "settings.read" },
    { path: "/dash/settings/traces", name: t("traces.settings.menuLabel"), perm: "integration.manage" },
    { path: "/dash/settings/clusters", name: t("clusters.menuLabel") },
    { path: "/dash/settings/security", name: t("settings.security.title"), perm: "settings.read" },
    { path: "/dash/settings/audit", name: t("auditLog.title"), perm: "team.manage" },
  ].filter((item) => !item.perm || can(item.perm));

  const isActive = (item) => {
    if (item.exact) return path === item.path;
    const prefixes = item.match || [item.path];
    return prefixes.some((p) => path === p || path.startsWith(`${p}/`));
  };

  const collapsed = !isOpen && !isSmallScreen;
  const closeOnMobile = () => isSmallScreen && setIsOpen(false);

  return (
    <>
      <nav
        className={`app-sidebar ${collapsed ? "is-collapsed" : ""} ${isSmallScreen ? "is-mobile" : ""} ${isSmallScreen && isOpen ? "is-open" : ""}`}
        aria-label={t("nav.primary", "Primary navigation")}
      >
        <div className="app-sidebar-brand">
          <NavLink to="/dash" className="app-sidebar-logo" onClick={closeOnMobile} aria-label="SerOps">
            <SerOpsMark size={22} className="app-sidebar-mark" />
            {!collapsed && <span className="app-sidebar-wordmark">SerOps</span>}
          </NavLink>
          {!isSmallScreen && (
            <button
              type="button"
              className="app-sidebar-collapse"
              onClick={() => setIsOpen(!isOpen)}
              aria-label={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
              title={collapsed ? t("nav.expandSidebar") : t("nav.collapseSidebar")}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          )}
        </div>

        {organisation && (
          <div className={`app-sidebar-org ${collapsed ? "is-collapsed" : ""}`} title={organisation}>
            <span className="app-sidebar-org-logo" aria-hidden="true">
              {orgLogo
                ? <img src={orgLogo} alt="" onError={() => setOrgLogo(null)} />
                : organisation.trim().charAt(0).toUpperCase()}
            </span>
            {!collapsed && <span className="app-sidebar-org-name">{organisation}</span>}
          </div>
        )}

        <div className="app-sidebar-scroll">
          {groups.map((group) => (
            <div className="app-nav-group" key={group.id}>
              {!collapsed && <div className="app-nav-group-label">{group.label}</div>}
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(item);
                return (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    end={item.exact}
                    className={`app-nav-item ${active ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    title={collapsed ? item.name : undefined}
                    onClick={closeOnMobile}
                  >
                    <Icon size={18} strokeWidth={1.75} aria-hidden="true" />
                    {!collapsed && <span className="app-nav-label">{item.name}</span>}
                  </NavLink>
                );
              })}
              {group.id === "configure" && (
                <>
                  <button
                    type="button"
                    className={`app-nav-item ${onSettings ? "active" : ""}`}
                    onClick={() => {
                      if (collapsed) setIsOpen(true);
                      setSettingsOpen(!settingsOpen);
                    }}
                    title={collapsed ? t("nav.settings") : undefined}
                    aria-expanded={settingsOpen}
                    aria-controls="app-settings-submenu"
                  >
                    <SlidersHorizontal size={18} strokeWidth={1.75} aria-hidden="true" />
                    {!collapsed && (
                      <>
                        <span className="app-nav-label">{t("nav.settings")}</span>
                        <span className="app-nav-chevron" aria-hidden="true">
                          {settingsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        </span>
                      </>
                    )}
                  </button>
                  {!collapsed && settingsOpen && (
                    <div className="app-subnav" id="app-settings-submenu">
                      {settingsItems.map((item) => (
                        <NavLink
                          key={item.path}
                          to={item.path}
                          end={item.exact}
                          className={({ isActive: a }) => `app-subnav-item ${a ? "active" : ""}`}
                          onClick={closeOnMobile}
                        >
                          {item.name}
                        </NavLink>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      </nav>

      {isSmallScreen && isOpen && (
        <button
          type="button"
          className="app-sidebar-backdrop"
          onClick={() => setIsOpen(false)}
          aria-label={t("nav.closeSidebar", "Close sidebar")}
        />
      )}
    </>
  );
};

export default Sidebar;
