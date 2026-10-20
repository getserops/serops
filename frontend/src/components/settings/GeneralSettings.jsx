/**
 * General Settings (Organisation Settings)
 * 
 * Contains only organisation-level settings:
 * - Logo
 * - Organisation name
 * - Website
 * 
 * User preferences (language, theme, timezone, date format) 
 * have been moved to the profile menu in the top bar.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Spinner } from 'react-bootstrap';
import { FaCamera } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { OrganisationService } from '../../services/organisation.service';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';
import PageHeader from '../PageHeader';
import { can } from '../../utils/permissions';

const GeneralSettings = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [uploadingLogo, setUploadingLogo] = useState(false);
    const fileInputRef = useRef(null);
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

    const handleLogoRemove = async () => {
        try {
            setUploadingLogo(true);
            await OrganisationService.removeLogo();
            setSettings(prev => ({ ...prev, logoUrl: null }));
            window.dispatchEvent(new CustomEvent('serops:org-updated', { detail: { logo_url: null } }));
            toast.success(t('common.success'));
        } catch (error) {
            console.error('Logo remove error:', error);
            toast.error(t('common.error'));
        } finally {
            setUploadingLogo(false);
        }
    };

    const handleLogoChange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;

        e.target.value = '';
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
            // The sidebar shows the organisation logo; let it follow.
            window.dispatchEvent(new CustomEvent('serops:org-updated', { detail: { logo_url: result.logo_url } }));
            toast.success(t('common.success'));
        } catch (error) {
            console.error('Logo upload error:', error);
            toast.error(error.response?.data?.logo?.[0] || t('common.error'));
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

            if (can('settings.manage')) {
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
            <PageHeader title={t('settings.general.title')} subtitle={t('settings.general.subtitle')} />

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
                        border: '2px dashed var(--border-hover)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        overflow: 'hidden',
                        backgroundColor: 'var(--bg-sunken)',
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
                    {settings.logoUrl && !uploadingLogo && (
                        <>
                            {' '}
                            <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={handleLogoRemove}>
                                {t('settings.general.organisation.removeLogo')}
                            </button>
                        </>
                    )}
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

            <div className="settings-page-actions">
                <button
                    className="btn btn-primary"
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
