/**
 * Settings Layout Component
 * Container for settings pages - navigation is now in main Sidebar
 */

import React, { useEffect, useRef, useState } from 'react';
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
    // One line on a phone; a tap shows the whole sentence.
    const [noticeOpen, setNoticeOpen] = useState(false);
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
                    <div
                        className={`settings-readonly-notice${noticeOpen ? ' is-expanded' : ''}`}
                        role="note"
                        title={t('demo.settingsReadOnly')}
                        onClick={() => setNoticeOpen((v) => !v)}
                    >
                        {t('demo.settingsReadOnly')}
                    </div>
                )}
                {alerting && (
                    <nav className="nav nav-tabs settings-subtabs" aria-label={t('nav.alertsRouting')} data-demo-allowed>
                        <NavLink to="/dash/settings/delivery" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                            {t('settings.delivery.title', 'Delivery channels')}
                        </NavLink>
                        <NavLink to="/dash/settings/routing-rules" className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
                            {t('settings.routing.title', 'Routing rules')}
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
