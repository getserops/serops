/**
 * UserMenu Component - Airflow Style
 * 
 * Dropdown menu at sidebar bottom with user preferences:
 * - Language selector (EN/FR)
 * - Appearance (Light/Dark/System)
 * - Timezone with current time
 * - Profile link
 * - Logout
 */

import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    FaUserCircle, FaSignOutAlt, FaChevronUp,
    FaLanguage, FaMoon, FaSun, FaDesktop, FaClock, FaUser
} from 'react-icons/fa';
import AuthService from '../../services/auth.service';
import './UserMenu.css';

// Timezone options
const TIMEZONES = [
    { value: 'UTC', label: 'UTC' },
    { value: 'Europe/London', label: 'London (GMT)' },
    { value: 'Europe/Paris', label: 'Paris (CET)' },
    { value: 'America/New_York', label: 'New York (EST)' },
    { value: 'America/Los_Angeles', label: 'Los Angeles (PST)' },
    { value: 'Asia/Tokyo', label: 'Tokyo (JST)' }
];

const UserMenu = ({ isCollapsed }) => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const menuRef = useRef(null);

    const [isOpen, setIsOpen] = useState(false);
    const [settings, setSettings] = useState({
        language: 'en',
        theme: 'system',
        timezone: 'UTC'
    });

    const user = JSON.parse(localStorage.getItem('user') || '{}');

    // Load settings on mount
    useEffect(() => {
        const saved = JSON.parse(localStorage.getItem('seropsSettings') || '{}');
        setSettings({
            language: i18n.language || saved.language || 'en',
            theme: saved.theme || 'system',
            timezone: saved.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
        });
    }, [i18n.language]);

    // Close menu when clicking outside
    useEffect(() => {
        const handleClickOutside = (event) => {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const saveSettings = (newSettings) => {
        localStorage.setItem('seropsSettings', JSON.stringify(newSettings));
        window.dispatchEvent(new CustomEvent('settingsChanged', { detail: newSettings }));
    };

    const handleLanguageChange = (lang) => {
        i18n.changeLanguage(lang);
        localStorage.setItem('seropsLanguage', lang);
        const newSettings = { ...settings, language: lang };
        setSettings(newSettings);
        saveSettings(newSettings);
    };

    const handleThemeChange = (theme) => {
        const newSettings = { ...settings, theme };
        setSettings(newSettings);
        saveSettings(newSettings);

        const root = document.documentElement;
        if (theme === 'system') {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            root.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
        } else {
            root.setAttribute('data-theme', theme);
        }
    };

    const handleTimezoneChange = (timezone) => {
        const newSettings = { ...settings, timezone };
        setSettings(newSettings);
        saveSettings(newSettings);
    };

    const handleLogout = async () => {
        try {
            await AuthService.logout();
        } catch (err) {
            console.error('Logout error:', err);
        }
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        navigate('/login');
        window.location.reload();
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

    const getTimezoneLabel = () => {
        const tz = TIMEZONES.find(t => t.value === settings.timezone);
        return tz ? tz.label : settings.timezone;
    };

    // Collapsed state - just show avatar icon
    if (isCollapsed) {
        return (
            <div className="user-menu-collapsed" onClick={() => navigate('/dash/Profile')}>
                <div className="user-avatar-small">
                    <FaUserCircle />
                </div>
            </div>
        );
    }

    return (
        <div className="user-menu" ref={menuRef}>
            {/* Trigger Button */}
            <div
                className="user-menu-trigger"
                onClick={() => setIsOpen(!isOpen)}
                data-testid="user-menu-trigger"
                role="button"
                aria-label="Open user menu"
                aria-expanded={isOpen}
                aria-haspopup="menu"
                tabIndex={0}
            >
                <div className="user-avatar">
                    <FaUserCircle size={20} />
                </div>
                <div className="user-info">
                    <span className="user-name">{user.first_name || user.username || 'User'}</span>
                </div>
                <FaChevronUp style={{
                    transform: isOpen ? 'rotate(0deg)' : 'rotate(180deg)',
                    transition: 'transform 0.2s',
                    color: '#999',
                    fontSize: '12px'
                }} />
            </div>

            {/* Dropdown Menu - Opens Upward */}
            {isOpen && (
                <div className="user-menu-dropdown">
                    {/* Language */}
                    <div className="menu-item">
                        <div className="menu-item-icon"><FaLanguage /></div>
                        <div className="menu-item-content">
                            <span className="menu-item-label">{t('settings.general.language.title')}</span>
                        </div>
                        <div className="menu-item-options">
                            <button
                                className={`menu-option ${settings.language === 'en' ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); handleLanguageChange('en'); }}
                            >
                                EN
                            </button>
                            <button
                                className={`menu-option ${settings.language === 'fr' ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); handleLanguageChange('fr'); }}
                            >
                                FR
                            </button>
                        </div>
                    </div>

                    {/* Appearance */}
                    <div className="menu-item">
                        <div className="menu-item-icon">
                            {settings.theme === 'dark' ? <FaMoon /> : settings.theme === 'light' ? <FaSun /> : <FaDesktop />}
                        </div>
                        <div className="menu-item-content">
                            <span className="menu-item-label">{t('settings.general.appearance.title')}</span>
                        </div>
                        <div className="menu-item-options">
                            <button
                                className={`menu-option ${settings.theme === 'light' ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); handleThemeChange('light'); }}
                                title="Light"
                            >
                                <FaSun />
                            </button>
                            <button
                                className={`menu-option ${settings.theme === 'dark' ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); handleThemeChange('dark'); }}
                                title="Dark"
                            >
                                <FaMoon />
                            </button>
                            <button
                                className={`menu-option ${settings.theme === 'system' ? 'active' : ''}`}
                                onClick={(e) => { e.stopPropagation(); handleThemeChange('system'); }}
                                title="System"
                            >
                                <FaDesktop />
                            </button>
                        </div>
                    </div>

                    {/* Timezone */}
                    <div className="menu-item">
                        <div className="menu-item-icon"><FaClock /></div>
                        <div className="menu-item-content">
                            <span className="menu-item-label">{t('settings.general.timezone.title')}</span>
                            <span className="menu-item-value">{getCurrentTime()} · {getTimezoneLabel()}</span>
                        </div>
                        <select
                            style={{
                                padding: '4px 8px',
                                border: '1px solid #e0e0e0',
                                borderRadius: '4px',
                                fontSize: '12px',
                                cursor: 'pointer',
                                background: 'white'
                            }}
                            value={settings.timezone}
                            onChange={(e) => { e.stopPropagation(); handleTimezoneChange(e.target.value); }}
                            onClick={(e) => e.stopPropagation()}
                        >
                            {TIMEZONES.map(tz => (
                                <option key={tz.value} value={tz.value}>{tz.label}</option>
                            ))}
                        </select>
                    </div>

                    <div className="menu-divider" />

                    {/* Profile */}
                    <div className="menu-item" onClick={() => { setIsOpen(false); navigate('/dash/Profile'); }}>
                        <div className="menu-item-icon"><FaUser /></div>
                        <span className="menu-item-label">{t('nav.profile')}</span>
                    </div>

                    {/* Logout */}
                    <div
                        className="menu-item logout"
                        onClick={handleLogout}
                        data-testid="user-menu-logout"
                        role="menuitem"
                        aria-label="Log out"
                        tabIndex={0}
                    >
                        <div className="menu-item-icon"><FaSignOutAlt /></div>
                        <span className="menu-item-label">{t('nav.logout')}</span>
                    </div>
                </div>
            )}
        </div>
    );
};

export default UserMenu;
