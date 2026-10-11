import React, { useEffect, useState } from "react";
import "./Sidebar.css";
import {
  FaProjectDiagram,
  FaCog,
  FaComments,
  FaExclamationCircle,
  FaChevronDown,
  FaChevronRight,
  FaBuilding,
  FaUsers,
  FaBell,
  FaRobot,
  FaDatabase,
  FaPlug,
  FaBars,
  FaShieldAlt,
  FaHistory,
  FaUserCircle,
  FaEnvelope,
  FaKey,
  FaServer,
} from "react-icons/fa";
import { RiDashboardHorizontalFill } from "react-icons/ri";
import useCapabilities from "../hooks/useCapabilities";
import { NavLink, useLocation } from "react-router-dom";
import { useMediaQuery } from "@mui/material";
import { useTranslation } from "react-i18next";
import { BsClipboardDataFill } from "react-icons/bs";

const Sidebar = ({ isOpen, setIsOpen }) => {
  const { t } = useTranslation();
  const isSmallScreen = useMediaQuery("(max-width: 860px)");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();
  const { has } = useCapabilities();

  const user = JSON.parse(localStorage.getItem("user")) || {};
  const [organisation, setOrganisation] = useState(
    user?.organisation_name || user?.organisation || null
  );

  // PR-D3 (2026-09-20): fall back to /api/organisation/current/ when
  // localStorage.user is stale or missing (e.g. token-only sessions
  // from Playwright, cookie-only refresh flow, or a user whose stored
  // shape predates the ``userinfo.organisation`` API change). Prevents
  // the "NO ORGANISATION" sidebar label the 2026-09-20 UI review
  // flagged.
  useEffect(() => {
    if (organisation) return;
    (async () => {
      try {
        const apiClient = (await import('../services/api-client')).default;
        const res = await apiClient.get('/organisation/info/');
        const name = res?.data?.name || res?.data?.organisation_name;
        if (name) {
          setOrganisation(name);
          try {
            const cur = JSON.parse(localStorage.getItem('user')) || {};
            localStorage.setItem('user', JSON.stringify({ ...cur, organisation: name }));
          } catch { /* localStorage may be blocked */ }
        }
      } catch {
        /* endpoint may not exist yet; keep sidebar blank rather than
         * shouting "NO ORGANISATION" — that read wrong more often
         * than it read right. */
      }
    })();
  }, [organisation]);

  // Auto-expand settings if on a settings page
  useEffect(() => {
    if (location.pathname.startsWith('/dash/settings')) {
      setSettingsOpen(true);
      if (!isOpen && !isSmallScreen) setIsOpen(true);
    }
  }, [location.pathname, isSmallScreen]);

  useEffect(() => {
    if (isSmallScreen) {
      setIsOpen(false);
    } else {
      setIsOpen(true);
    }
  }, [isSmallScreen]);

  const menuItems = [
    {
      path: "/dash",
      name: t('nav.dashboard'),
      icon: <RiDashboardHorizontalFill />,
      exact: true,
    },
    {
      path: "/dash/projects",
      name: t('nav.projects'),
      icon: <FaProjectDiagram />,
    },
    {
      path: "/dash/data",
      name: t('nav.data'),
      icon: <BsClipboardDataFill />,
    },
    {
      path: "/dash/issues",
      name: t('nav.issues'),
      icon: <FaExclamationCircle />,
    },
    {
      path: "/dash/chat",
      name: t('nav.aiChat'),
      icon: <FaComments />,
    },
    // Note: no top-level "Traces" nav entry. Traces are a data source
    // (like logs / metrics / code changes / CI-CD logs) and are
    // rendered inline on batch detail via BatchTraces, plus surfaced
    // as "related traces" on issue detail (Item #12a). Keeping Traces
    // out of the sidebar matches the peer pattern of the other data
    // sources — none of them get a sidebar entry either. The
    // /dash/traces/* routes still exist (BatchTraces, TraceDetail) but
    // are only reached by context-linking from a batch or issue, not
    // top-level exploration. Ingest-key management stays under
    // Settings → Traces for admins.
  ];

  const settingsItems = [
    {
      path: "/dash/settings",
      name: t('settings.general.menuLabel'),
      icon: <FaBuilding />,
      exact: true,
    },
    {
      path: "/dash/settings/team",
      name: t('settings.team.title'),
      icon: <FaUsers />,
    },
    {
      path: "/dash/settings/delivery",
      name: t('settings.delivery.title', 'Delivery Channels'),
      icon: <FaBell />,
    },
    {
      path: "/dash/settings/routing-rules",
      name: t('settings.routing.title', 'Routing Rules'),
      icon: <FaBell />,
    },
    {
      path: "/dash/settings/ai",
      name: t('settings.ai.title'),
      icon: <FaRobot />,
    },
    {
      path: "/dash/settings/sentinel",
      name: "Sentinel",
      icon: <FaShieldAlt />,
    },
    {
      path: "/dash/settings/data",
      name: t('settings.data.title'),
      icon: <FaDatabase />,
    },
    {
      path: "/dash/settings/integrations",
      name: t('globalIntegrations.title'),
      icon: <FaPlug />,
    },
    // Ingest-key management page — same visibility rule as the main
    // Traces nav entry. A user with no traces setup should not be
    // pushed into an empty API-key page.
    ...(has('traces') ? [{
      path: "/dash/settings/traces",
      name: t('traces.settings.menuLabel'),
      icon: <FaKey />,
    }] : []),
    // Cluster management — only useful for K8s installs, but always
    // visible under Settings so users discover the feature. Empty
    // state on the page itself guides them.
    {
      path: "/dash/settings/clusters",
      name: t('clusters.menuLabel'),
      icon: <FaServer />,
    },
    // PR-N phase 2: this entry used to point at /settings/incident-channels,
    // which now redirects to /settings/delivery — it duplicated the
    // "Delivery Channels" item above. Removed.
    {
      path: "/dash/settings/security",
      name: t('settings.security.title'),
      icon: <FaShieldAlt />,
    },
    {
      path: "/dash/settings/audit",
      name: t('auditLog.title'),
      icon: <FaHistory />,
    },
  ];

  const toggleSidebar = () => setIsOpen(!isOpen);

  return (
    <>
      <nav
        className={`sidebar-container ${isOpen ? 'sidebar-expanded' : 'sidebar-collapsed'} ${isSmallScreen && isOpen ? 'mobile-open' : ''}`}
        aria-label={t('nav.primary', 'Primary navigation')}
      >
        {/* Header */}
        <div className="sidebar-header">
          {isOpen ? (
            <button
              type="button"
              className="sidebar-logo-button"
              onClick={toggleSidebar}
              aria-label={t('nav.collapseSidebar', 'Collapse sidebar')}
              style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
            >
              <img
                src="/assets/images/Serops-Logo.png"
                alt="SerOps"
                className="sidebar-logo"
                onError={(e) => {
                  e.target.style.display = 'none';
                  e.target.nextSibling.style.display = 'block';
                }}
              />
            </button>
          ) : (
            <button
              type="button"
              className="sidebar-toggle"
              onClick={toggleSidebar}
              aria-label={t('nav.expandSidebar', 'Expand sidebar')}
            >
              <FaBars />
            </button>
          )}
          <h2
            style={{
              display: 'none',
              color: 'var(--primary)',
              margin: 0,
              fontSize: '24px',
              fontWeight: 'bold',
              cursor: 'pointer'
            }}
            onClick={toggleSidebar}
          >
            SerOps
          </h2>
        </div>

        {/* Organization Info — hidden entirely when we couldn't
            resolve a name (see fetch fallback above). Reads cleaner
            than the previous "NO ORGANISATION" placeholder. */}
        {isOpen && organisation && (
          <div className="sidebar-org">
            <div className="org-name">{organisation}</div>
          </div>
        )}

        {/* Navigation Links */}
        <div className="sidebar-nav">
          {menuItems.map((item, index) => (
            <NavLink
              to={item.path}
              key={index}
              className={({ isActive }) =>
                `nav-item ${isActive && (item.exact ? location.pathname === item.path : location.pathname.startsWith(item.path)) ? 'active' : ''}`
              }
              title={!isOpen ? item.name : ''}
              onClick={() => isSmallScreen && setIsOpen(false)}
            >
              <div className="nav-icon">{item.icon}</div>
              <span className="nav-label">{item.name}</span>
            </NavLink>
          ))}

          {/* Settings Group */}
          <div className="settings-group">
            <button
              type="button"
              className={`nav-item ${location.pathname.startsWith('/dash/settings') ? 'active' : ''}`}
              onClick={() => {
                if (!isOpen) setIsOpen(true);
                setSettingsOpen(!settingsOpen);
              }}
              title={!isOpen ? t('nav.settings') : ''}
              aria-expanded={settingsOpen}
              aria-controls="sidebar-settings-submenu"
              style={{ background: 'none', border: 'none', width: '100%', textAlign: 'left' }}
            >
              <div className="nav-icon"><FaCog /></div>
              <span className="nav-label" style={{ flex: 1 }}>{t('nav.settings')}</span>
              {isOpen && (
                <span className="settings-chevron" aria-hidden="true">
                  {settingsOpen ? <FaChevronDown /> : <FaChevronRight />}
                </span>
              )}
            </button>

            {/* Settings Submenu */}
            {isOpen && settingsOpen && (
              <div className="settings-submenu" id="sidebar-settings-submenu">
                {settingsItems.map((item, index) => (
                  <NavLink
                    to={item.path}
                    key={index}
                    className={({ isActive }) => `sub-nav-item ${isActive ? 'active' : ''}`}
                    end={item.exact}
                    onClick={() => isSmallScreen && setIsOpen(false)}
                  >
                    <div className="sub-nav-icon">{item.icon}</div>
                    <span>{item.name}</span>
                  </NavLink>
                ))}
              </div>
            )}
          </div>
        </div>
      </nav>

      {/* Mobile Backdrop — button so keyboard users can dismiss too. */}
      {isSmallScreen && isOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          onClick={() => setIsOpen(false)}
          aria-label={t('nav.closeSidebar', 'Close sidebar')}
        />
      )}
    </>
  );
};

export default Sidebar;
