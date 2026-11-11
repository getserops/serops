/**
 * Settings → Enterprise license: show, install or remove the install-wide
 * license key (platform staff, or the admin of a single-organisation
 * install). Keys are verified by the backend, offline.
 */
import React, { useEffect, useState } from 'react';
import { Button, Form, Spinner } from 'react-bootstrap';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import apiClient from '../../services/api-client';
import PageHeader from '../../components/PageHeader';
import CollapsibleSection from '../../components/settings/CollapsibleSection';
import { refreshEdition } from '../../utils/edition';
import '../../components/settings/SettingsLayout.css';

const STATUS_TONE = { valid: 'ds-chip-ok', expired: 'ds-chip-warn', invalid: 'ds-chip-err' };

const errorMessage = (error, fallback) => error?.response?.data?.error || fallback;

const LicenseSettings = () => {
    const { t } = useTranslation();
    const [license, setLicense] = useState(null);
    const [loading, setLoading] = useState(true);
    const [keyText, setKeyText] = useState('');
    const [file, setFile] = useState(null);
    const [saving, setSaving] = useState(false);

    const load = async () => {
        try {
            const res = await apiClient.get('/ee/license/');
            setLicense(res.data);
        } catch {
            setLicense({ status: 'none' });
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { load(); }, []);

    const install = async (event) => {
        event.preventDefault();
        setSaving(true);
        try {
            let res;
            if (file) {
                const body = new FormData();
                body.append('file', file);
                res = await apiClient.put('/ee/license/', body);
            } else {
                res = await apiClient.put('/ee/license/', { license: keyText });
            }
            setLicense(res.data);
            setKeyText('');
            setFile(null);
            event.target.reset();
            refreshEdition();
            toast.success(t('ee.license.installed'));
        } catch (error) {
            toast.error(errorMessage(error, t('ee.license.installFailed')));
        } finally {
            setSaving(false);
        }
    };

    const remove = async () => {
        if (!window.confirm(t('ee.license.removeConfirm'))) return;
        try {
            await apiClient.delete('/ee/license/');
            setLicense({ status: 'none' });
            refreshEdition();
            toast.success(t('ee.license.removed'));
        } catch (error) {
            toast.error(errorMessage(error, t('common.error')));
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

    const status = license?.status || 'none';
    const statusLabel = { valid: t('ee.license.statusValid'), expired: t('ee.license.statusExpired'), invalid: t('ee.license.statusInvalid') }[status];

    return (
        <div className="settings-section">
            <PageHeader title={t('ee.license.title')} subtitle={t('ee.license.subtitle')} />

            <CollapsibleSection
                title={t('ee.license.currentTitle')}
                description={t('ee.license.currentDesc')}
                actions={status !== 'none' && (
                    <Button variant="outline-danger" size="sm" onClick={remove}>{t('ee.license.remove')}</Button>
                )}
            >
                {status === 'none' ? (
                    <p className="mb-0 text-muted">{t('ee.license.none')}</p>
                ) : (
                    <div>
                        <div className="ds-kv">
                            <span>{t('ee.license.status')}</span>
                            <span><span className={`badge ds-chip ${STATUS_TONE[status]}`}>{statusLabel}</span></span>
                        </div>
                        {license.licensee && (
                            <div className="ds-kv"><span>{t('ee.license.licensee')}</span><span>{license.licensee}</span></div>
                        )}
                        {license.expires && (
                            <div className="ds-kv"><span>{t('ee.license.expires')}</span><span>{license.expires}</span></div>
                        )}
                        {license.id && (
                            <div className="ds-kv"><span>{t('ee.license.licenseId')}</span><span className="ds-mono">{license.id}</span></div>
                        )}
                        {license.features?.length > 0 && (
                            <div className="ds-kv">
                                <span>{t('ee.license.features')}</span>
                                <span className="d-flex flex-wrap justify-content-end gap-1">
                                    {license.features.map((code) => (
                                        <span key={code} className="badge ds-chip ds-chip-neutral">{license.feature_labels?.[code] || code}</span>
                                    ))}
                                </span>
                            </div>
                        )}
                        {status === 'expired' && <p className="form-hint mt-3 mb-0">{t('ee.license.expiredNote')}</p>}
                        {status === 'invalid' && <p className="form-hint mt-3 mb-0">{t('ee.license.invalidNote', { error: license.error })}</p>}
                    </div>
                )}
            </CollapsibleSection>

            <CollapsibleSection title={t('ee.license.installTitle')} description={t('ee.license.installDesc')}>
                <Form onSubmit={install}>
                    <Form.Group controlId="ee-license-key" className="mb-3">
                        <Form.Label>{t('ee.license.keyLabel')}</Form.Label>
                        <Form.Control
                            as="textarea"
                            rows={6}
                            className="ds-mono"
                            value={keyText}
                            onChange={(e) => setKeyText(e.target.value)}
                            disabled={Boolean(file)}
                            spellCheck={false}
                        />
                    </Form.Group>
                    <Form.Group controlId="ee-license-file" className="mb-2">
                        <Form.Label>{t('ee.license.fileLabel')}</Form.Label>
                        <Form.Control type="file" accept=".json,.license,application/json,text/plain" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                    </Form.Group>
                    <p className="form-hint">{t('ee.license.offlineHint')}</p>
                    <div className="settings-page-actions">
                        <Button type="submit" variant="primary" disabled={saving || (!keyText.trim() && !file)}>
                            {saving && <Spinner as="span" animation="border" size="sm" className="me-2" />}
                            {t('ee.license.install')}
                        </Button>
                    </div>
                </Form>
            </CollapsibleSection>
        </div>
    );
};

export default LicenseSettings;
