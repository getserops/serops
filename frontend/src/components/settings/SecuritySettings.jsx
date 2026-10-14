
import React, { useState, useEffect } from 'react';
import { Spinner } from 'react-bootstrap';
import { FaShieldAlt, FaClock, FaTimes, FaCloud } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import { toast } from 'react-toastify';
import enterpriseSettingsService from '../../services/enterpriseSettings.service';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';

const SecuritySettings = () => {
    const { t } = useTranslation();
    const [settings, setSettings] = useState(null);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    // Form state - session timeout only (password policy enforced at creation time)
    const [sessionTimeout, setSessionTimeout] = useState(480);

    useEffect(() => {
        loadSettings();
    }, []);

    const loadSettings = async () => {
        try {
            setLoading(true);
            const [securityData, ssoData] = await Promise.all([
                enterpriseSettingsService.getSecuritySettings(),
                enterpriseSettingsService.getSSOConfig().catch(() => null) // Handle 404/Error gracefully
            ]);

            // /auth/sso/config speaks sso_* field names; the form uses short ones.
            const sso = ssoData ? {
                enabled: ssoData.sso_enabled,
                provider: ssoData.sso_provider,
                client_id: ssoData.sso_client_id,
                discovery_url: ssoData.sso_discovery_url,
                sso_client_secret_configured: ssoData.sso_client_secret_configured,
                redirect_uri: ssoData.sso_redirect_uri,
            } : (securityData.sso || {});
            setSettings({ ...securityData, sso });

            // Load session timeout
            if (securityData && securityData.session) {
                setSessionTimeout(securityData.session.timeout_minutes);
            }
        } catch (err) {
            toast.error(t('security.loadFailed'));
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);

            // Save security settings (session timeout)
            await enterpriseSettingsService.updateSecuritySettings({
                session: { timeout_minutes: sessionTimeout }
            });

            // Save SSO settings if modified
            if (settings.sso) {
                const ssoPayload = {
                    sso_enabled: settings.sso.enabled,
                    sso_provider: settings.sso.provider,

                    // OIDC
                    sso_client_id: settings.sso.client_id,
                    sso_discovery_url: settings.sso.discovery_url,
                };
                // Only include client_secret if user actually entered a new one
                if (settings.sso.client_secret) {
                    ssoPayload.sso_client_secret = settings.sso.client_secret;
                }
                await enterpriseSettingsService.updateSSOConfig(ssoPayload);
            }

            toast.success(t('security.saveSuccess'));

            // Reload to get fresh state (e.g. secret configured flag)
            loadSettings();
        } catch (err) {
            toast.error(t('security.saveFailed'));
            console.error(err);
        } finally {
            setSaving(false);
        }
    };

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" variant="primary" />
                <p className="mt-2 text-muted">{t('security.loading')}</p>
            </div>
        );
    }

    return (
        <div className="settings-section">
            <div className="settings-header">
                <div className="settings-icon-wrapper security">
                    <FaShieldAlt />
                </div>
                <div>
                    <h2>{t('security.title')}</h2>
                    <p>{t('security.subtitle')}</p>
                </div>
            </div>

            {/* Password Policy section removed - validation enforced during password creation */}

            {/* Session Timeout */}
            <CollapsibleSection
                title={t('security.sessionManagement')}
                description={t('security.sessionManagementDesc')}
            >
                <div className="form-group">
                    <label className="settings-form-label mb-3">{t('security.sessionTimeoutDuration')}</label>
                    <div className="settings-selection-grid">
                        {[
                            { val: 30, label: '30m' },
                            { val: 60, label: '1h' },
                            { val: 240, label: '4h' },
                            { val: 480, label: '8h' },
                            { val: 1440, label: '24h' },
                            { val: 0, label: t('security.never') }
                        ].map(({ val, label }) => (
                            <div
                                key={val}
                                className={`settings-selection-card ${sessionTimeout === val ? 'active' : ''}`}
                                onClick={() => setSessionTimeout(val)}
                            >
                                <div className="settings-selection-icon">
                                    {val === 0 ? <FaShieldAlt /> : <FaClock />}
                                </div>
                                <span className="settings-selection-label">{label}</span>
                                <span className="settings-selection-desc">
                                    {val === 0 ? t('security.noAutoLogout') : t('security.inactivityLimit')}
                                </span>
                            </div>
                        ))}
                    </div>
                    <small className="form-text text-muted mt-2">
                        {t('security.sessionTimeoutHint')}
                    </small>
                </div>
            </CollapsibleSection>

            {/* SSO Status */}
            <CollapsibleSection
                title={t('security.sso')}
                description={t('security.ssoDesc')}
            >
                <div className="sso-config-section">
                    {/* Protocol Selection */}
                    <div className="form-group mb-4">
                        <label className="settings-form-label">{t('security.authenticationProtocol')}</label>
                        <div className="settings-selection-grid">
                            <div
                                key="oidc"
                                className={`settings-selection-card ${settings?.sso?.provider === 'oidc' ? 'active' : ''}`}
                                onClick={() => setSettings(prev => ({
                                    ...prev,
                                    sso: { ...prev.sso, provider: 'oidc', enabled: true }
                                }))}
                            >
                                <div className="settings-selection-icon"><FaCloud /></div>
                                <span className="settings-selection-label">OPENID CONNECT</span>
                                <span className="settings-selection-desc">Okta, Azure AD, Google, Keycloak</span>
                            </div>

                            <div
                                className={`settings-selection-card ${settings?.sso?.provider === 'none' ? 'active' : ''}`}
                                onClick={() => setSettings(prev => ({
                                    ...prev,
                                    sso: { ...prev.sso, provider: 'none', enabled: false }
                                }))}
                            >
                                <div className="settings-selection-icon"><FaTimes /></div>
                                <span className="settings-selection-label">{t('security.disabled')}</span>
                            </div>
                        </div>
                    </div>

                    {/* OIDC Configuration */}
                    {settings?.sso?.provider === 'oidc' && (
                        <div className="settings-form-panel">
                            <h5 className="mb-3">OpenID Connect Configuration</h5>
                            {settings?.sso?.redirect_uri && (
                                <div className="form-group mb-3">
                                    <label htmlFor="sso-redirect-uri">{t('security.redirectUri')}</label>
                                    <input
                                        id="sso-redirect-uri"
                                        type="text"
                                        className="form-control"
                                        value={settings.sso.redirect_uri}
                                        readOnly
                                        onFocus={(e) => e.target.select()}
                                    />
                                    <small className="text-muted">{t('security.redirectUriHint')}</small>
                                </div>
                            )}
                            <div className="row">
                                <div className="col-md-6">
                                    <div className="form-group mb-3">
                                        <label>{t('security.clientId')}</label>
                                        <input
                                            type="text"
                                            className="form-control"
                                            value={settings?.sso?.client_id || ''}
                                            onChange={(e) => setSettings(prev => ({
                                                ...prev,
                                                sso: { ...(prev?.sso || {}), client_id: e.target.value }
                                            }))}
                                            placeholder="e.g., serops-dashboard"
                                        />
                                    </div>
                                </div>
                                <div className="col-md-6">
                                    <div className="form-group mb-3">
                                        <label>{t('security.clientSecret')}</label>
                                        <input
                                            type="password"
                                            className="form-control"
                                            value={settings?.sso?.client_secret || ''}
                                            onChange={(e) => setSettings(prev => ({
                                                ...prev,
                                                sso: { ...(prev?.sso || {}), client_secret: e.target.value }
                                            }))}
                                            placeholder={settings?.sso?.sso_client_secret_configured ? t('security.configured') : "Paste Client Secret"}
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className="form-group mb-3">
                                <label>{t('security.discoveryUrl')}</label>
                                <input
                                    type="url"
                                    className="form-control"
                                    value={settings?.sso?.discovery_url || ''}
                                    onChange={(e) => setSettings(prev => ({
                                        ...prev,
                                        sso: { ...(prev?.sso || {}), discovery_url: e.target.value }
                                    }))}
                                    placeholder="https://idp.example.com/.well-known/openid-configuration"
                                />
                            </div>
                        </div>
                    )}

                </div>
            </CollapsibleSection>

            {/* Save Button */}
            <div className="d-flex justify-content-end mt-4">
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

export default SecuritySettings;
