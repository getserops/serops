import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from 'react-i18next';
import ClusterPicker from "./ClusterPicker";
import { OPEN_EVENT as OPEN_PALETTE } from "./CommandPalette";
import { MdPerson } from "react-icons/md";
import { RiLogoutBoxLine } from "react-icons/ri";
import { FaBell } from 'react-icons/fa';
import { Bell, Menu, Search } from 'lucide-react';
import EnvironmentPicker from './EnvironmentPicker';
import { AnimatePresence } from 'framer-motion';
import AuthService from "../services/auth.service";
import { Dropdown } from "react-bootstrap";
import ProfileService from "../services/profile.service";
import NotificationService from "../services/notification.service";
import NotificationPanel from "./NotificationPanel";
import { applyTheme, applyDensity } from "../utils/theme";

function Navbar({ isOpen, avatar, toggleSidebar }) {
  const { t } = useTranslation();
  const BACKEND_HOST = import.meta.env.VITE_BASE_URL;
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [selectedItem, setSelectedItem] = useState(null);
  const [user, setUser] = useState(null);
  const [image, setImage] = useState('');
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => { setImageFailed(false); }, [image]);
  const [showNotifications, setShowNotifications] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const navigate = useNavigate();

  // User preferences state
  const [settings, setSettings] = useState({
    language: 'en',
    theme: 'system',
    timezone: 'UTC',
    dateFormat: 'iso'
  });

  // Timezone options
  const TIMEZONES = [
    { value: 'UTC', label: 'UTC' },
    { value: 'Europe/Paris', label: 'Paris (CET)' },
    { value: 'Europe/London', label: 'London (GMT)' },
    { value: 'America/New_York', label: 'New York (EST)' },
    { value: 'America/Los_Angeles', label: 'Los Angeles (PST)' },
    { value: 'Asia/Tokyo', label: 'Tokyo (JST)' }
  ];

  useEffect(() => {
    // Load user preferences
    const saved = JSON.parse(localStorage.getItem('seropsSettings') || '{}');
    setSettings(prev => ({
      ...prev,
      language: localStorage.getItem('seropsLanguage') || saved.language || 'en',
      theme: saved.theme || 'system',
      density: saved.density || 'comfortable',
      timezone: saved.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      dateFormat: saved.dateFormat || 'iso'
    }));

    const userData = AuthService.getUser();
    if (userData && userData._id) {
      ProfileService.getOne(userData._id, {})
        .then((res) => {
          setImage(res.data.avatar);
        })
        .catch((err) => {
          console.error("Error:", err);
        });
    }
    try {
      const my_user = JSON.parse(localStorage.getItem('user'));
      if (my_user && my_user.avatar) {
        setImage(my_user.avatar);
      }
    } catch (e) {
      console.error("Error parsing user from local storage", e);
    }

    if (userData) {
      setUser(userData);
    }

    const fetchUnreadCount = async () => {
      try {
        const response = await NotificationService.getUnreadCount();
        setUnreadCount(response.data.unread_count);
      } catch (err) {
        console.error("Error fetching unread count:", err);
      }
    };

    fetchUnreadCount();
  }, []);

  useEffect(() => {
    if (showNotifications) {
      const fetchUnreadCount = async () => {
        try {
          const response = await NotificationService.getUnreadCount();
          setUnreadCount(response.data.unread_count);
        } catch (err) {
          console.error("Error fetching unread count:", err);
        }
      };

      fetchUnreadCount();
    }
  }, [showNotifications]);

  const saveSettings = (newSettings) => {
    localStorage.setItem('seropsSettings', JSON.stringify(newSettings));
    window.dispatchEvent(new CustomEvent('settingsChanged', { detail: newSettings }));
  };

  const handleLanguageChange = (lang) => {
    // Dynamically import i18n to change language
    import('../i18n').then(({ default: i18n }) => {
      i18n.changeLanguage(lang);
    });
    localStorage.setItem('seropsLanguage', lang);
    const newSettings = { ...settings, language: lang };
    setSettings(newSettings);
    saveSettings(newSettings);
  };

  const handleThemeChange = (theme) => {
    const newSettings = { ...settings, theme };
    setSettings(newSettings);
    saveSettings(newSettings);

    applyTheme(theme);
  };

  const handleDensityChange = (density) => {
    const newSettings = { ...settings, density };
    setSettings(newSettings);
    saveSettings(newSettings);
    applyDensity(density);
  };

  const handleTimezoneChange = (timezone) => {
    const newSettings = { ...settings, timezone };
    setSettings(newSettings);
    saveSettings(newSettings);
  };

  const handleDateFormatChange = (dateFormat) => {
    const newSettings = { ...settings, dateFormat };
    setSettings(newSettings);
    saveSettings(newSettings);
  };

  const handleLogout = async () => {
    try {
      await AuthService.logout();
      localStorage.removeItem("token");
      localStorage.removeItem("user");
      navigate('/login');
    } catch (err) {
      if (err.response && err.response.status === 401) {
        localStorage.removeItem("token");
        localStorage.removeItem("user");
        navigate('/login');
      } else {
      }
    }
  };

  const toggleDropdown = () => {
    setDropdownOpen((prevState) => !prevState);
  };

  const toggleNotifications = () => {
    setShowNotifications((prev) => !prev);
  };

  const getFullName = () => {
    if (user) {
      return `${user.first_name} ${user.last_name}`;
    }
    return "";
  };

  // Shown when the user has no avatar (or it fails to load).
  const getInitials = () => {
    if (!user) return "?";
    const fromName = `${(user.first_name || "").trim()[0] || ""}${(user.last_name || "").trim()[0] || ""}`;
    return (fromName || (user.username || user.email || "?")[0]).toUpperCase();
  };

  const getCurrentTime = () => {
    try {
      return new Date().toLocaleTimeString(settings.language === 'fr' ? 'fr-FR' : 'en-US', {
        timeZone: settings.timezone,
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return '--:--';
    }
  };

  return (
    <>
      <header className="app-topbar">
        <button
          type="button"
          className="app-topbar-icon app-topbar-menu"
          onClick={toggleSidebar}
          aria-label={t('nav.openMenu')}
        >
          <Menu size={20} aria-hidden="true" />
        </button>
        <EnvironmentPicker />
        {/* Cluster picker (Item #19) — visible only for multi-cluster orgs. */}
        <ClusterPicker />
        <div className="app-topbar-spacer" />
          <button type="button" className="command-palette-trigger" aria-label={t('palette.title')}
                  onClick={() => window.dispatchEvent(new Event(OPEN_PALETTE))}>
            <Search size={15} aria-hidden="true" />
            <span className="command-palette-trigger-label">{t('palette.trigger')}</span>
            <kbd className="command-palette-kbd">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'}</kbd>
          </button>
          <button
            type="button"
            className="app-topbar-icon"
            onClick={toggleNotifications}
            aria-label={unreadCount > 0 ? t('nav.notificationsUnread', { count: unreadCount }) : t('nav.notifications')}
            aria-expanded={showNotifications}
          >
            <Bell size={18} strokeWidth={1.75} aria-hidden="true" />
            {unreadCount > 0 && (
              <span className="app-topbar-badge" aria-hidden="true">
                {unreadCount > 99 ? '99+' : unreadCount}
              </span>
            )}
          </button>

          {/* User Profile Dropdown */}
          <Dropdown show={dropdownOpen} onToggle={toggleDropdown}>
            <Dropdown.Toggle as="div" id="userDropdown" className="app-topbar-user"
                             data-testid="user-menu-trigger"
                             aria-label="Open user menu"
                             role="button"
                             tabIndex={0}>
              <span className="d-none d-xl-inline account-user-name">
                {getFullName()}
              </span>
              {image && !imageFailed ? (
                <img
                  className="img-profile rounded-circle"
                  src={`${BACKEND_HOST}${image}`}
                  onError={() => setImageFailed(true)}
                  alt="Profile"
                  style={{ width: "32px", height: "32px", objectFit: "cover" }}
                />
              ) : (
                <span
                  className="img-profile rounded-circle"
                  aria-label="Profile"
                  style={{ width: "32px", height: "32px", display: "inline-flex", alignItems: "center", justifyContent: "center", background: "var(--tone-brand-soft)", color: "var(--tone-brand-text)", fontWeight: 700, fontSize: "12px" }}
                >
                  {getInitials()}
                </span>
              )}
            </Dropdown.Toggle>

            <Dropdown.Menu align="end" style={{
              border: 'none',
              boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
              borderRadius: '12px',
              padding: '12px',
              minWidth: '280px'
            }}>
              {/* Profile - at top like Jira */}
              <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-default)' }}>
                <Dropdown.Item onClick={() => navigate("/dash/Profile")} style={{ borderRadius: '8px', padding: '10px 12px', margin: '-4px -12px' }}>
                  <MdPerson style={{ marginRight: '10px', color: 'var(--text-secondary)', fontSize: '18px' }} />
                  {t('nav.profile')}
                </Dropdown.Item>
                <Dropdown.Item onClick={() => navigate("/dash/settings/preferences")} style={{ borderRadius: '8px', padding: '10px 12px', margin: '-4px -12px' }}>
                  <FaBell style={{ marginRight: '10px', color: 'var(--text-secondary)', fontSize: '18px' }} />
                  {t('preferences.title')}
                </Dropdown.Item>
              </div>

              {/* Language */}
              <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase' }}>
                  {t('settings.general.language.title')}
                </div>
                <select
                  value={settings.language}
                  onChange={(e) => handleLanguageChange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    cursor: 'pointer',
                    background: 'var(--bg-card)', color: 'var(--text-primary)'
                  }}
                >
                  <option value="en">{settings.language === 'en' ? '✓ ' : ''}{t('languages.en')}</option>
                  <option value="fr">{settings.language === 'fr' ? '✓ ' : ''}{t('languages.fr')}</option>
                </select>
              </div>

              {/* Appearance */}
              <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase' }}>
                  {t('settings.general.appearance.title')}
                </div>
                <select
                  value={settings.theme}
                  onChange={(e) => handleThemeChange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    cursor: 'pointer',
                    background: 'var(--bg-card)', color: 'var(--text-primary)'
                  }}
                >
                  <option value="light">{settings.theme === 'light' ? '✓ ' : ''}{t('settings.general.appearance.light')}</option>
                  <option value="dark">{settings.theme === 'dark' ? '✓ ' : ''}{t('settings.general.appearance.dark')}</option>
                  <option value="system">{settings.theme === 'system' ? '✓ ' : ''}{t('settings.general.appearance.system')}</option>
                </select>
                <select
                  value={settings.density || 'comfortable'}
                  onChange={(e) => handleDensityChange(e.target.value)}
                  aria-label={t('density.label')}
                  className="mt-2"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    cursor: 'pointer',
                    background: 'var(--bg-card)', color: 'var(--text-primary)'
                  }}
                >
                  <option value="comfortable">{t('density.comfortable')}</option>
                  <option value="compact">{t('density.compact')}</option>
                </select>
              </div>

              {/* Timezone */}
              <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border-default)' }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '8px', textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
                  <span>{t('settings.general.timezone.title')}</span>
                  <span style={{ color: 'var(--text-link)' }}>{getCurrentTime()}</span>
                </div>
                <select
                  value={settings.timezone}
                  onChange={(e) => handleTimezoneChange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    fontSize: '13px',
                    cursor: 'pointer',
                    background: 'var(--bg-card)', color: 'var(--text-primary)'
                  }}
                >
                  {TIMEZONES.map(tz => (
                    <option key={tz.value} value={tz.value}>{settings.timezone === tz.value ? '✓ ' : ''}{tz.label}</option>
                  ))}
                </select>
              </div>

              {/* Logout */}
              <div style={{ padding: '4px 0', marginTop: '4px' }}>
                <Dropdown.Item onClick={handleLogout}
                               data-testid="user-menu-logout"
                               aria-label="Log out"
                               style={{ borderRadius: '8px', padding: '10px 12px', color: 'var(--tone-red-text)' }}>
                  <RiLogoutBoxLine style={{ marginRight: '10px', fontSize: '18px' }} />
                  {t('nav.logout')}
                </Dropdown.Item>
              </div>
            </Dropdown.Menu>
          </Dropdown>
      </header>

      {/* Notification Panel */}
      <AnimatePresence>
        {showNotifications && (
          <NotificationPanel
            onClose={() => setShowNotifications(false)}
            unreadCount={unreadCount}
            setUnreadCount={setUnreadCount}
          />
        )}
      </AnimatePresence>
    </>
  );
}


export default Navbar;
