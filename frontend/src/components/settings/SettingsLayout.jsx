/**
 * Settings Layout Component
 * Container for settings pages - navigation is now in main Sidebar
 */

import React, { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { Container } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { isDemoUser } from '../../utils/demo';
import { lockWriteControls } from '../../utils/demoReadOnlyControls';
import './SettingsLayout.css';

const SettingsLayout = () => {
    const { t } = useTranslation();
    const contentRef = useRef(null);
    const demo = isDemoUser();
    const { pathname } = useLocation();
    // Delivery channels and routing rules are one sidebar entry
    // ("Alerts & routing"); a tab strip switches between them.
    const alerting = pathname.startsWith('/dash/settings/delivery') || pathname.startsWith('/dash/settings/routing-rules');
    const reason = t('demo.controlDisabled');
    useEffect(() => {
        if (!demo || !contentRef.current) return undefined;
        return lockWriteControls(contentRef.current, reason);
    }, [demo, reason]);
    return (
        <div className="settings-page">
            <Container fluid>
                {demo && (
                    <div className="settings-readonly-notice" role="note">{t('demo.settingsReadOnly')}</div>
                )}
                {alerting && (
                    <nav className="nav nav-tabs settings-subtabs" aria-label={t('nav.alertsRouting')} data-demo-allowed>
                        <NavLink to="/dash/settings/delivery" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                            {t('settings.delivery.title', 'Delivery Channels')}
                        </NavLink>
                        <NavLink to="/dash/settings/routing-rules" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                            {t('settings.routing.title', 'Routing Rules')}
                        </NavLink>
                    </nav>
                )}
                <div className="settings-content" ref={contentRef}>
                    <Outlet />
                </div>
            </Container>
        </div>
    );
};

export default SettingsLayout;
