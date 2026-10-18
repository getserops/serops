/**
 * Data Retention Settings Component
 * Data usage visualization, auto-retention policies, and manual cleanup
 */


import React, { useState, useEffect } from 'react';
import { Form, Button, Spinner } from 'react-bootstrap';
import { FaExclamationTriangle } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import DataService from '../../services/data.service';
import enterpriseSettingsService from '../../services/enterpriseSettings.service';
import CollapsibleSection from './CollapsibleSection';
import ChoiceGroup from './ChoiceGroup';
import './SettingsLayout.css';
import PageHeader from '../PageHeader';

const DataSettings = () => {
    const { t } = useTranslation();
    // Manual cleanup
    const [deleteDays, setDeleteDays] = useState(7);
    const [deleting, setDeleting] = useState(false);

    // Data usage
    const [dataUsage, setDataUsage] = useState(null);
    const [loadingUsage, setLoadingUsage] = useState(true);

    // Retention policy
    const [policy, setPolicy] = useState(null);
    const [loadingPolicy, setLoadingPolicy] = useState(true);
    const [savingPolicy, setSavingPolicy] = useState(false);

    // Batch interval
    const [formBatchInterval, setFormBatchInterval] = useState(15);
    const [savingBatchInterval, setSavingBatchInterval] = useState(false);

    // Form state
    const [formPolicy, setFormPolicy] = useState({
        auto_cleanup_enabled: false,
        retention_days: 30,
        cleanup_frequency: 'weekly',
        audit_log_retention_days: 90
    });

    // Issue deduplication settings
    const [issueSettings, setIssueSettings] = useState(null);
    const [loadingIssueSettings, setLoadingIssueSettings] = useState(true);
    const [savingIssueSettings, setSavingIssueSettings] = useState(false);
    const [formIssueSettings, setFormIssueSettings] = useState({
        dedup_enabled: true,
        dedup_window_days: 7,
        default_mute_duration_days: 7,
        auto_resolve_enabled: false,
        auto_resolve_after_days: 7,
        // Past-incident memory (server-side default values mirror IssueSettings)
        memory_enabled: true,
        memory_window_days: 90,
        memory_max_items: 3
    });

    useEffect(() => {
        loadDataUsage();
        loadRetentionPolicy();
        loadIssueSettings();
    }, []);

    const loadDataUsage = async () => {
        try {
            setLoadingUsage(true);
            const data = await enterpriseSettingsService.getDataUsage();
            setDataUsage(data);
        } catch (error) {
            console.error('Failed to load data usage:', error);
        } finally {
            setLoadingUsage(false);
        }
    };

    const loadRetentionPolicy = async () => {
        try {
            setLoadingPolicy(true);
            const data = await enterpriseSettingsService.getRetentionPolicy();
            setPolicy(data);
            setFormBatchInterval(data.batch_generation_interval ?? 10);
            setFormPolicy({
                auto_cleanup_enabled: data.auto_cleanup_enabled,
                retention_days: data.retention_days,
                cleanup_frequency: data.cleanup_frequency,
                audit_log_retention_days: data.audit_log_retention_days
            });
        } catch (error) {
            console.error('Failed to load retention policy:', error);
        } finally {
            setLoadingPolicy(false);
        }
    };

    const loadIssueSettings = async () => {
        try {
            setLoadingIssueSettings(true);
            const data = await enterpriseSettingsService.getIssueSettings();
            setIssueSettings(data);
            setFormIssueSettings({
                dedup_enabled: data.dedup_enabled,
                dedup_window_days: data.dedup_window_days,
                default_mute_duration_days: data.default_mute_duration_days,
                auto_resolve_enabled: data.auto_resolve_enabled,
                auto_resolve_after_days: data.auto_resolve_after_days,
                memory_enabled: data.memory_enabled ?? true,
                memory_window_days: data.memory_window_days ?? 90,
                memory_max_items: data.memory_max_items ?? 3
            });
        } catch (error) {
            console.error('Failed to load issue settings:', error);
        } finally {
            setLoadingIssueSettings(false);
        }
    };

    const handleDeleteBatches = async () => {
        if (!window.confirm(t('dataRetention.deleteConfirm', { days: deleteDays }))) {
            return;
        }

        try {
            setDeleting(true);
            const result = await DataService.deleteOldBatches(deleteDays);
            toast.success(result.message || t('dataRetention.deleteSuccess'));
            loadDataUsage(); // Refresh usage stats
        } catch (error) {
            toast.error(error.response?.data?.error || t('dataRetention.deleteFailed'));
        } finally {
            setDeleting(false);
        }
    };

    const handleSavePolicy = async () => {
        try {
            setSavingPolicy(true);
            await enterpriseSettingsService.updateRetentionPolicy(formPolicy);
            toast.success(t('dataRetention.policySaved'));
            loadRetentionPolicy();
        } catch (error) {
            toast.error(t('dataRetention.policySaveFailed'));
        } finally {
            setSavingPolicy(false);
        }
    };

    const handleSaveBatchInterval = async () => {
        try {
            setSavingBatchInterval(true);
            await enterpriseSettingsService.updateRetentionPolicy({ batch_generation_interval: formBatchInterval });
            toast.success(t('batchInterval.saved'));
            loadRetentionPolicy();
        } catch (error) {
            toast.error(t('batchInterval.saveFailed'));
        } finally {
            setSavingBatchInterval(false);
        }
    };

    const handleSaveIssueSettings = async () => {
        try {
            setSavingIssueSettings(true);
            await enterpriseSettingsService.updateIssueSettings(formIssueSettings);
            toast.success(t('issueSettings.dedup.saved'));
            loadIssueSettings();
        } catch (error) {
            toast.error(t('issueSettings.dedup.saveFailed'));
        } finally {
            setSavingIssueSettings(false);
        }
    };

    const formatNumber = (num) => {
        if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
        return num?.toString() || '0';
    };

    const getFrequencyLabel = (freq) => {
        const labels = {
            daily: t('dataRetention.daily'),
            weekly: t('dataRetention.weekly'),
            monthly: t('dataRetention.monthly')
        };
        return labels[freq] || freq;
    };

    const getDedupWindowLabel = (days) => {
        if (days === 0) return t('issueSettings.dedup.forever');
        return t('issueSettings.dedup.days', { count: days });
    };

    const getMuteDurationLabel = (days) => {
        if (days === 0) return t('issueSettings.dedup.forever');
        if (days === 1) return t('issueSettings.dedup.oneDay');
        if (days === 7) return t('issueSettings.dedup.oneWeek');
        return t('issueSettings.dedup.days', { count: days });
    };

    return (
        <div className="settings-section">
            <PageHeader title={t('dataRetention.title')} subtitle={t('dataRetention.subtitle')} />

            {/* Data Usage Section */}
            <CollapsibleSection
                title={t('dataRetention.dataUsage')}
                description={t('dataRetention.dataUsageDesc')}
                defaultExpanded={true}
            >
                {loadingUsage ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <div className="row">
                        <div className="col-md-6 mb-4 mb-md-0">
                            <label className="settings-form-label">{t('dataRetention.totalRecords')}</label>
                            <div className="d-flex align-items-baseline gap-2 mb-2">
                                <h2 className="mb-0 text-primary">{dataUsage?.total_records?.toLocaleString() || 0}</h2>
                                <small className="text-muted">{t('dataRetention.records')}</small>
                            </div>
                            <div className="usage-bar-container">
                                <div
                                    className="usage-bar-fill"
                                    style={{ width: `${Math.min((dataUsage?.total_records || 0) / 100, 100)}%` }}
                                />
                            </div>
                        </div>
                        <div className="col-md-6">
                            <label className="settings-form-label">{t('dataRetention.breakdown')}</label>
                            <div className="d-flex flex-column gap-2 mt-1">
                                <div className="d-flex justify-content-between">
                                    <span className="text-muted">{t('dataRetention.batches')}</span>
                                    <strong>{formatNumber(dataUsage?.totals?.batches)}</strong>
                                </div>
                                <div className="d-flex justify-content-between">
                                    <span className="text-muted">{t('dataRetention.issues')}</span>
                                    <strong>{formatNumber(dataUsage?.totals?.issues)}</strong>
                                </div>
                                <div className="d-flex justify-content-between">
                                    <span className="text-muted">{t('dataRetention.pipelines')}</span>
                                    <strong>{formatNumber(dataUsage?.totals?.pipelines)}</strong>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </CollapsibleSection>

            {/* Issue Deduplication Section */}
            <CollapsibleSection
                title={t('issueSettings.dedup.title')}
                description={t('issueSettings.dedup.subtitle')}
            >
                {loadingIssueSettings ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <>
                        <label className="toggle-item large">
                            <div className="toggle-label">
                                <span>{t('issueSettings.dedup.enable')}</span>
                                <small>{t('issueSettings.dedup.enableHint')}</small>
                            </div>
                            <input
                                type="checkbox"
                                checked={formIssueSettings.dedup_enabled}
                                onChange={(e) => setFormIssueSettings({ ...formIssueSettings, dedup_enabled: e.target.checked })}
                            />
                            <span className="toggle-slider"></span>
                        </label>

                        <fieldset className="settings-dependent" disabled={!formIssueSettings.dedup_enabled}>
                            <ChoiceGroup
                                label={t('issueSettings.dedup.window')}
                                value={formIssueSettings.dedup_window_days}
                                onChange={(days) => setFormIssueSettings({ ...formIssueSettings, dedup_window_days: days })}
                                options={[7, 14, 30, 90, 0].map((days) => ({ value: days, label: getDedupWindowLabel(days) }))}
                            />
                            <ChoiceGroup
                                label={t('issueSettings.dedup.muteDuration')}
                                value={formIssueSettings.default_mute_duration_days}
                                onChange={(days) => setFormIssueSettings({ ...formIssueSettings, default_mute_duration_days: days })}
                                options={[1, 7, 30, 0].map((days) => ({ value: days, label: getMuteDurationLabel(days) }))}
                            />
                            <label className="toggle-item large">
                                <div className="toggle-label">
                                    <span>{t('issueSettings.dedup.autoResolve')}</span>
                                    <small>{t('issueSettings.dedup.autoResolveHint', { days: formIssueSettings.auto_resolve_after_days })}</small>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={formIssueSettings.auto_resolve_enabled}
                                    onChange={(e) => setFormIssueSettings({ ...formIssueSettings, auto_resolve_enabled: e.target.checked })}
                                />
                                <span className="toggle-slider"></span>
                            </label>
                        </fieldset>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSaveIssueSettings}
                                disabled={savingIssueSettings}
                            >
                                {savingIssueSettings ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </>
                )}
            </CollapsibleSection>

            {/* Past-Incident Memory Section */}
            <CollapsibleSection
                title={t('issueSettings.memory.title')}
                description={t('issueSettings.memory.subtitle')}
            >
                {loadingIssueSettings ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <>
                        <label className="toggle-item large">
                            <div className="toggle-label">
                                <span>{t('issueSettings.memory.enable')}</span>
                                <small>{t('issueSettings.memory.enableHint')}</small>
                            </div>
                            <input
                                type="checkbox"
                                checked={formIssueSettings.memory_enabled}
                                onChange={(e) => setFormIssueSettings({ ...formIssueSettings, memory_enabled: e.target.checked })}
                            />
                            <span className="toggle-slider"></span>
                        </label>

                        <fieldset className="settings-dependent" disabled={!formIssueSettings.memory_enabled}>
                            <ChoiceGroup
                                label={t('issueSettings.memory.window')}
                                value={formIssueSettings.memory_window_days}
                                onChange={(days) => setFormIssueSettings({ ...formIssueSettings, memory_window_days: days })}
                                options={[30, 60, 90, 180, 365].map((days) => ({ value: days, label: t('issueSettings.dedup.days', { count: days }) }))}
                            />
                            <ChoiceGroup
                                label={t('issueSettings.memory.maxItems')}
                                hint={t('issueSettings.memory.maxItemsHint')}
                                value={formIssueSettings.memory_max_items}
                                onChange={(n) => setFormIssueSettings({ ...formIssueSettings, memory_max_items: n })}
                                options={[1, 2, 3, 5, 10].map((n) => ({ value: n, label: String(n) }))}
                            />
                        </fieldset>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSaveIssueSettings}
                                disabled={savingIssueSettings}
                            >
                                {savingIssueSettings ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </>
                )}
            </CollapsibleSection>

            {/* Batch Generation Interval Section */}
            <CollapsibleSection
                title={t('batchInterval.title')}
                description={t('batchInterval.subtitle')}
            >
                {loadingPolicy ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <>
                        <div className="ds-choice">
                            <label className="ds-choice-label" htmlFor="batch-interval">{t('batchInterval.interval')}</label>
                            <select
                                id="batch-interval"
                                className="form-select settings-select"
                                value={formBatchInterval}
                                onChange={(e) => setFormBatchInterval(parseInt(e.target.value))}
                            >
                                <optgroup label={t('batchInterval.minutesGroup')}>
                                    {[5, 10, 15, 20, 30, 45].map(mins => (
                                        <option key={mins} value={mins}>
                                            {mins === 15
                                                ? `${mins} ${t('batchInterval.minutes')} (${t('batchInterval.recommended')})`
                                                : `${mins} ${t('batchInterval.minutes')}`}
                                        </option>
                                    ))}
                                </optgroup>
                                <optgroup label={t('batchInterval.hoursGroup')}>
                                    {[60, 120, 240, 360, 720].map(mins => (
                                        <option key={mins} value={mins}>
                                            {mins === 60
                                                ? `1 ${t('batchInterval.hour')}`
                                                : `${mins / 60} ${t('batchInterval.hours')}`}
                                        </option>
                                    ))}
                                </optgroup>
                            </select>
                            <div className="ds-choice-hint">{t('batchInterval.hint')}</div>
                        </div>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSaveBatchInterval}
                                disabled={savingBatchInterval}
                            >
                                {savingBatchInterval ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </>
                )}
            </CollapsibleSection>

            {/* Retention Policy Section */}
            <CollapsibleSection
                title={t('dataRetention.retentionPolicy')}
                description={t('dataRetention.retentionPolicyDesc')}
            >
                {loadingPolicy ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <>
                        <label className="toggle-item large">
                            <div className="toggle-label">
                                <span>{t('dataRetention.enableAutoCleanup')}</span>
                                <small>{t('dataRetention.autoCleanupDesc')}</small>
                            </div>
                            <input
                                type="checkbox"
                                checked={formPolicy.auto_cleanup_enabled}
                                onChange={(e) => setFormPolicy({ ...formPolicy, auto_cleanup_enabled: e.target.checked })}
                            />
                            <span className="toggle-slider"></span>
                        </label>

                        <fieldset className="settings-dependent" disabled={!formPolicy.auto_cleanup_enabled}>
                            <ChoiceGroup
                                label={t('dataRetention.retentionPeriod')}
                                value={formPolicy.retention_days}
                                onChange={(days) => setFormPolicy({ ...formPolicy, retention_days: days })}
                                options={[7, 14, 30, 60, 90, 180, 365].map((days) => ({ value: days, label: `${days} ${t('dataRetention.days')}` }))}
                            />
                            <ChoiceGroup
                                label={t('dataRetention.cleanupFrequency')}
                                value={formPolicy.cleanup_frequency}
                                onChange={(freq) => setFormPolicy({ ...formPolicy, cleanup_frequency: freq })}
                                options={['daily', 'weekly', 'monthly'].map((freq) => ({ value: freq, label: getFrequencyLabel(freq) }))}
                            />
                        </fieldset>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSavePolicy}
                                disabled={savingPolicy}
                            >
                                {savingPolicy ? t('common.saving') : t('dataRetention.savePolicy')}
                            </button>
                        </div>
                    </>
                )}
            </CollapsibleSection>

            {/* Manual Cleanup Section */}
            <CollapsibleSection
                className="ds-settings-section-danger"
                title={t('dataRetention.manualCleanup')}
                description={t('dataRetention.manualCleanupDesc')}
            >
                <div className="settings-inline-form">
                    <div className="ds-choice">
                        <label className="ds-choice-label" htmlFor="delete-older-than">{t('dataRetention.deleteBatchesOlderThan')}</label>
                        <select
                            id="delete-older-than"
                            className="form-select settings-select"
                            value={deleteDays}
                            onChange={(e) => setDeleteDays(parseInt(e.target.value))}
                        >
                            {[1, 3, 7, 14, 30, 60].map(d => (
                                <option key={d} value={d}>{d} {t('dataRetention.days')}</option>
                            ))}
                        </select>
                    </div>
                    <Button
                        variant="danger"
                        onClick={handleDeleteBatches}
                        disabled={deleting}
                    >
                        {deleting ? t('dataRetention.deleting') : t('dataRetention.deleteNow')}
                    </Button>
                </div>
                <div className="ds-choice-hint ds-choice-hint-danger">
                    <FaExclamationTriangle aria-hidden="true" />
                    {t('dataRetention.irreversibleWarning')}
                </div>
            </CollapsibleSection>
        </div>
    );
};

export default DataSettings;

