/**
 * General Settings (Organisation Settings)
 * 
 * Contains only organisation-level settings:
 * - Logo
 * - Organisation name
 * - Website
 * 
 * User preferences (language, theme, timezone, date format) 
 * have been moved to the UserMenu in the sidebar.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Spinner } from 'react-bootstrap';
import { FaBuilding, FaCamera } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { OrganisationService } from '../../services/organisation.service';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';

const GeneralSettings = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [uploadingLogo, setUploadingLogo] = useState(false);
    const fileInputRef = useRef(null);
    const [isAdmin, setIsAdmin] = useState(false);
    const [settings, setSettings] = useState({
        orgName: '',
        website: '',
        logoUrl: null
    });

    useEffect(() => {
        loadSettings();
    }, []);

    const loadSettings = async () => {
        try {
            setLoading(true);
            const user = JSON.parse(localStorage.getItem('user') || '{}');
            setIsAdmin(user.role === 'admin');

            // Load from backend
            let orgData = {};
            try {
                orgData = await OrganisationService.getOrganisationInfo();
            } catch (err) {
                console.error('Failed to load org info:', err);
            }

            setSettings({
                orgName: orgData.name || user.organisation || '',
                website: orgData.website || '',
                logoUrl: orgData.logo_url || null
            });
        } catch (error) {
            console.error('Failed to load settings:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleChange = (field, value) => {
        setSettings(prev => ({ ...prev, [field]: value }));
    };

    const handleLogoClick = () => {
        fileInputRef.current?.click();
    };

    const handleLogoChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        if (!file.type.startsWith('image/')) {
            toast.error('Please select an image file');
            return;
        }

        if (file.size > 2 * 1024 * 1024) {
            toast.error('Image must be less than 2MB');
            return;
        }

        try {
            setUploadingLogo(true);
            const result = await OrganisationService.uploadLogo(file);
            setSettings(prev => ({ ...prev, logoUrl: result.logo_url }));
            toast.success(t('common.success'));
        } catch (error) {
            console.error('Logo upload error:', error);
            toast.error(t('common.error'));
        } finally {
            setUploadingLogo(false);
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            const updateData = {
                website: settings.website
            };

            if (isAdmin) {
                updateData.name = settings.orgName;
            }

            await OrganisationService.updateOrganisationInfo(updateData);
            toast.success(t('common.success'));
        } catch (error) {
            toast.error(t('common.error'));
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" variant="primary" />
                <p className="mt-3 text-muted">{t('common.loading')}</p>
            </div>
        );
    }

    return (
        <div className="settings-section">
            <div className="settings-header mb-4">
                <div className="settings-icon-wrapper primary">
                    <FaBuilding />
                </div>
                <div>
                    <h2>{t('settings.general.title')}</h2>
                    <p>{t('settings.general.subtitle')}</p>
                </div>
            </div>

            <CollapsibleSection
                title={t('settings.general.organisation.title')}
                description={t('settings.general.organisation.subtitle')}
                defaultExpanded={true}
            >
                {/* Logo Upload */}
                <div
                    className="logo-upload-container mb-4"
                    onClick={handleLogoClick}
                    style={{
                        width: '80px',
                        height: '80px',
                        borderRadius: '12px',
                        border: '2px dashed var(--border-color, #dee2e6)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        overflow: 'hidden',
                        backgroundColor: 'var(--bg-secondary, #f8f9fa)',
                        position: 'relative'
                    }}
                >
                    {uploadingLogo ? (
                        <Spinner animation="border" size="sm" />
                    ) : settings.logoUrl ? (
                        <img
                            src={settings.logoUrl}
                            alt="Organisation Logo"
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                    ) : (
                        <FaCamera size={24} className="text-muted" />
                    )}
                </div>
                <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/*"
                    onChange={handleLogoChange}
                    style={{ display: 'none' }}
                />
                <small className="text-muted d-block mb-4">
                    {t('settings.general.organisation.logoHint')}
                </small>

                {/* Organisation Name */}
                <div className="form-group mb-3">
                    <label className="settings-form-label">
                        {t('settings.general.organisation.name')}
                    </label>
                    <input
                        type="text"
                        className="form-control"
                        value={settings.orgName}
                        disabled
                        title="Organisation name is used for data indexing and cannot be changed safely."
                    />
                    <small className="text-muted">
                        Changes to organisation name are restricted to prevent data loss (metrics & logs dependency).
                    </small>
                </div>

                {/* Website */}
                <div className="form-group">
                    <label className="settings-form-label">
                        {t('settings.general.organisation.website')}
                    </label>
                    <input
                        type="url"
                        className="form-control"
                        value={settings.website}
                        onChange={(e) => handleChange('website', e.target.value)}
                        placeholder={t('settings.general.organisation.websitePlaceholder')}
                    />
                </div>
            </CollapsibleSection>

            <div className="d-flex justify-content-end mt-5">
                <button
                    className="settings-save-btn text-white"
                    onClick={handleSave}
                    disabled={saving}
                >
                    {saving ? t('common.saving') : t('common.saveChanges')}
                </button>
            </div>
        </div>
    );
};

export default GeneralSettings;
