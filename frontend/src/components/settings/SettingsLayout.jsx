/**
 * Settings Layout Component
 * Container for settings pages - navigation is now in main Sidebar
 */

import React, { useEffect, useRef } from 'react';
import { Outlet } from 'react-router-dom';
import { Container } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { isDemoUser } from '../../utils/demo';
import { lockWriteControls } from '../../utils/demoReadOnlyControls';
import './SettingsLayout.css';

const SettingsLayout = () => {
    const { t } = useTranslation();
    const contentRef = useRef(null);
    const demo = isDemoUser();
    const reason = t('demo.controlDisabled');
    useEffect(() => {
        if (!demo || !contentRef.current) return undefined;
        return lockWriteControls(contentRef.current, reason);
    }, [demo, reason]);
    return (
        <div className="settings-page">
            <Container fluid className="py-4">
                {demo && (
                    <div className="settings-readonly-notice" role="note">{t('demo.settingsReadOnly')}</div>
                )}
                <div className="settings-content" ref={contentRef}>
                    <Outlet />
                </div>
            </Container>
        </div>
    );
};

export default SettingsLayout;
