/**
 * Sentinel Intelligence Settings Component
 * Controls for enabling/disabling active gating mode and tuning thresholds
 */

import React, { useState, useEffect } from 'react';
import { Spinner } from 'react-bootstrap';
import { FaSlidersH } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import SettingsService from '../../services/settings.service';
import DashboardService from '../../services/dash.service';
import { useCluster } from '../../context/ClusterContext';
import SentinelStatsCard from '../SentinelStatsCard';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';
import PageHeader from '../PageHeader';

const SentinelSettings = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [config, setConfig] = useState({
        active_mode: true,
        error_spike_multiplier: 0,
        z_score_threshold: 0,
        max_quiet_batches: 12,
    });

    // What Sentinel did in the last 7 days (was a card on the Overview),
    // for the environment and cluster picked in the top bar.
    const { currentCluster, loading: clustersLoading, filter } = useCluster();
    const clusterId = clustersLoading ? null : (currentCluster?.id ?? null);
    const environment = filter?.environment || 'all';
    const { data: sentinelStats, isLoading: loadingStats } = useQuery({
        queryKey: ['sentinel-stats', environment, clusterId],
        queryFn: () => DashboardService.getSentinelStats(7, environment),
        staleTime: 2 * 60 * 1000,
        refetchInterval: 2 * 60 * 1000,
    });

    useEffect(() => {
        loadConfig();
    }, []);

    const loadConfig = async () => {
        try {
            setLoading(true);
            const data = await SettingsService.getSentinelConfig();
            setConfig({
                active_mode: data.active_mode,
                error_spike_multiplier: data.error_spike_multiplier,
                z_score_threshold: data.z_score_threshold,
                max_quiet_batches: data.max_quiet_batches,
            });
        } catch (error) {
            console.error('Failed to load sentinel config:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            await SettingsService.updateSentinelConfig(config);
            toast.success(t('sentinel.saved'));
        } catch (error) {
            toast.error(t('sentinel.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="settings-section">
            <PageHeader title={t('sentinel.title')} subtitle={t('sentinel.subtitle')} />

            <div className="settings-stats-panel">
                <SentinelStatsCard data={sentinelStats} loading={loadingStats} />
            </div>

            {/* Active Mode Toggle */}
            <CollapsibleSection
                title={t('sentinel.activeGating.title')}
                description={t('sentinel.activeGating.description')}
                defaultExpanded={true}
            >
                {loading ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <>
                        <div className="toggle-item large mb-4">
                            <div className="toggle-label">
                                <span>{t('sentinel.enableActiveMode')}</span>
                                <small>
                                    {config.active_mode
                                        ? t('sentinel.activeModeOn')
                                        : t('sentinel.activeModeOff')}
                                </small>
                            </div>
                            <label className="settings-toggle-switch">
                                <input aria-label={t('sentinel.enableActiveMode')}
                                    type="checkbox"
                                    checked={config.active_mode}
                                    onChange={(e) => setConfig({ ...config, active_mode: e.target.checked })}
                                />
                                <span className="toggle-slider"></span>
                            </label>
                        </div>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSave}
                                disabled={saving}
                            >
                                {saving ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </>
                )}
            </CollapsibleSection>

            {/* Threshold Overrides */}
            <CollapsibleSection
                title={t('sentinel.thresholds.title')}
                description={t('sentinel.thresholds.description')}
            >
                {loading ? (
                    <div className="text-center py-4"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <div className="settings-form-panel">
                        <div className="form-group mb-4">
                            <label className="settings-form-label">
                                <FaSlidersH className="me-2" />
                                {t('sentinel.errorSpikeMultiplier')}
                            </label>
                            <small className="text-muted d-block mb-2">
                                {t('sentinel.errorSpikeHint')}
                            </small>
                            <input aria-label={t('sentinel.errorSpikeMultiplier')}
                                type="number"
                                className="form-control"
                                style={{ maxWidth: 200 }}
                                value={config.error_spike_multiplier}
                                onChange={(e) => setConfig({ ...config, error_spike_multiplier: parseFloat(e.target.value) || 0 })}
                                min="0"
                                max="10"
                                step="0.5"
                            />
                        </div>

                        <div className="form-group mb-4">
                            <label className="settings-form-label">
                                <FaSlidersH className="me-2" />
                                {t('sentinel.zScoreThreshold')}
                            </label>
                            <small className="text-muted d-block mb-2">
                                {t('sentinel.zScoreHint')}
                            </small>
                            <input aria-label={t('sentinel.zScoreThreshold')}
                                type="number"
                                className="form-control"
                                style={{ maxWidth: 200 }}
                                value={config.z_score_threshold}
                                onChange={(e) => setConfig({ ...config, z_score_threshold: parseFloat(e.target.value) || 0 })}
                                min="0"
                                max="10"
                                step="0.5"
                            />
                        </div>

                        <div className="form-group mb-4">
                            <label className="settings-form-label">
                                <FaSlidersH className="me-2" />
                                {t('sentinel.maxQuietBatches')}
                            </label>
                            <small className="text-muted d-block mb-2">
                                {t('sentinel.maxQuietHint')}
                            </small>
                            <input aria-label={t('sentinel.maxQuietBatches')}
                                type="number"
                                className="form-control"
                                style={{ maxWidth: 200 }}
                                value={config.max_quiet_batches}
                                onChange={(e) => setConfig({ ...config, max_quiet_batches: parseInt(e.target.value) || 12 })}
                                min="1"
                                max="100"
                                step="1"
                            />
                        </div>

                        <div className="settings-section-footer">
                            <button
                                className="btn btn-primary"
                                onClick={handleSave}
                                disabled={saving}
                            >
                                {saving ? t('common.saving') : t('common.save')}
                            </button>
                        </div>
                    </div>
                )}
            </CollapsibleSection>
        </div>
    );
};

export default SentinelSettings;
