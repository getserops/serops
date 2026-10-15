/**
 * Settings Layout Component
 * Container for settings pages - navigation is now in main Sidebar
 */

import React from 'react';
import { Outlet } from 'react-router-dom';
import { Container } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { isDemoUser } from '../../utils/demo';
import './SettingsLayout.css';

const SettingsLayout = () => {
    const { t } = useTranslation();
    return (
        <div className="settings-page">
            <Container fluid className="py-4">
                {isDemoUser() && (
                    <div className="settings-readonly-notice" role="note">{t('demo.settingsReadOnly')}</div>
                )}
                <div className="settings-content">
                    <Outlet />
                </div>
            </Container>
        </div>
    );
};

export default SettingsLayout;
