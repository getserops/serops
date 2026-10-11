/**
 * Settings Layout Component
 * Container for settings pages - navigation is now in main Sidebar
 */

import React from 'react';
import { Outlet } from 'react-router-dom';
import { Container } from 'react-bootstrap';
import './SettingsLayout.css';

const SettingsLayout = () => {
    return (
        <div className="settings-page">
            <Container fluid className="py-4">
                <div className="settings-content">
                    <Outlet />
                </div>
            </Container>
        </div>
    );
};

export default SettingsLayout;
