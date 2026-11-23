/**
 * ObservabilityModal — connect a log/metric source.
 *
 * SerOps is log-centric for AI RCA, so we default the "logs"
 * capability to on and require the user to pick a logs-capable
 * provider. Metrics can be toggled if the provider supports both.
 *
 * Security posture:
 *   - password field: type=password + autoComplete=new-password.
 *   - password never persisted to localStorage; component state
 *     resets on close/unmount.
 *   - Backend encrypts at rest (Fernet) via ObservabilityIntegration.set_password.
 *   - Extra-config JSON hints (api_key, region) are also captured
 *     as free-text but sent to the backend which scrubs on response
 *     display (never re-echoed after create).
 *   - We don't console.log the payload — even at error time we only
 *     surface the backend's error message string, never the request.
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { liveTested, liveTestedDetail } from '../../../utils/integrationMaturity';
import {
    Alert,
    Box,
    Button,
    Checkbox,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    FormControlLabel,
    FormGroup,
    FormHelperText,
    InputLabel,
    MenuItem,
    Select,
    TextField,
    Typography,
} from '@mui/material';

import apiClient from '../../../services/api-client';

// Each store's own address, not an Elasticsearch one for all (E5).
const HOST_PLACEHOLDERS = {
    elasticsearch: 'http://elasticsearch:9200',
    opensearch: 'https://opensearch:9200',
    loki: 'http://loki:3100',
    splunk: 'https://splunk:8089',
    datadog: 'datadoghq.com',
};

// What a source without logs is for, in the provider list: trace stores were
// all labelled "metrics only" (E4).
const notLogsLabel = (caps, t) => (caps.includes('metrics') ? t('observabilityModal.metricsOnly') : t('observabilityModal.tracesOnly'));

const LOGS_ONLY_WARNING = 'observabilityModal.logsRequired';

export default function ObservabilityModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
    const [providers, setProviders] = useState([]);
    const [providerCode, setProviderCode] = useState('');
    const [displayName, setDisplayName] = useState('');
    const [capabilities, setCapabilities] = useState([]);
    const [host, setHost] = useState('');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [apiKey, setApiKey] = useState('');
    // Datadog searches logs and queries metrics with an application key.
    const [appKey, setAppKey] = useState('');
    const [awsRegion, setAwsRegion] = useState('');
    // Google Cloud: the project to read, and whether the services run on
    // GKE (Kubernetes metrics per workload) or on Compute Engine VMs.
    const [gcpProject, setGcpProject] = useState('');
    const [onGke, setOnGke] = useState(true);
    // Where the logs are: an index pattern (Elasticsearch / OpenSearch) or
    // log groups (CloudWatch). Optional: the backend has defaults.
    const [logLocation, setLogLocation] = useState('');
    const [loadingProviders, setLoadingProviders] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [error, setError] = useState(null);

    const resetState = () => {
        setProviderCode('');
        setDisplayName('');
        setCapabilities([]);
        setHost('');
        setUsername('');
        setPassword('');
        setApiKey('');
        setAppKey('');
        setAwsRegion('');
        setLogLocation('');
        setTestResult(null);
        setError(null);
    };

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        (async () => {
            setLoadingProviders(true);
            try {
                const { data } = await apiClient.get('/integrations/observability/providers/');
                if (!cancelled) {
                    setProviders(data || []);
                    setLoadingProviders(false);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(t('observabilityModal.loadFailed'));
                    setLoadingProviders(false);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [open, t]);

    useEffect(() => {
        if (!open) resetState();
    }, [open]);

    const selectedProvider = providers.find((p) => p.code === providerCode);
    const availableCaps = selectedProvider?.capabilities || [];
    const supportsLogs = availableCaps.includes('logs');
    const supportsMetrics = availableCaps.includes('metrics');
    // CloudWatch authenticates with the integration's own access key:
    // key ID in username, secret in the encrypted password field.
    const isAws = providerCode === 'cloudwatch';
    const isGcp = providerCode === 'gcp';
    const usesIndexPattern = providerCode === 'elasticsearch' || providerCode === 'opensearch';

    // On provider change, auto-fill display name + preselect
    // best-guess capabilities (logs preferred).
    useEffect(() => {
        if (!selectedProvider) return;
        if (!displayName) setDisplayName(selectedProvider.name);
        const preselected = [];
        if (supportsLogs) preselected.push('logs');
        if (supportsMetrics && !supportsLogs) preselected.push('metrics');
        setCapabilities(preselected);
        // Note: we intentionally don't reset user-entered credentials
        // on provider change — user might be switching to a similar
        // provider and re-entering the URL/password is annoying.
    }, [providerCode, selectedProvider]); // eslint-disable-line react-hooks/exhaustive-deps

    const toggleCapability = (cap) => {
        setCapabilities((prev) =>
            prev.includes(cap) ? prev.filter((c) => c !== cap) : [...prev, cap]
        );
    };

    const canSubmit = () => {
        if (!selectedProvider || saving || testing) return false;
        if (!displayName.trim()) return false;
        if (capabilities.length === 0) return false;
        // Enforce logs capability for wizard use — the onboarding
        // step's completion detector requires it.
        if (!capabilities.includes('logs')) return false;
        // Host is required for most providers; only exception is
        // cloudwatch/gcp/azure which authenticate via cloud SDK.
        const cloudProviders = new Set(['cloudwatch', 'gcp', 'azure']);
        if (!cloudProviders.has(selectedProvider.code) && !host.trim()) return false;
        if (isAws && !(username.trim() && password)) return false;
        // The project and its service-account key: without them the
        // integration saved and every query failed (GKE live test).
        if (isGcp && !(gcpProject.trim() && password)) return false;
        if (providerCode === 'datadog' && !(apiKey && appKey)) return false;
        return true;
    };

    const buildPayload = () => {
        const extra = {};
        if (apiKey && !isAws && !isGcp) extra.api_key = apiKey;
        if (isGcp) extra.project_id = gcpProject.trim();
        if (appKey && providerCode === 'datadog') extra.app_key = appKey;
        if (isAws && awsRegion.trim()) extra.aws_region = awsRegion.trim();
        if (logLocation.trim()) {
            if (isAws) extra.log_groups = logLocation.trim();
            else if (usesIndexPattern) extra.index_pattern = logLocation.trim();
        }
        const payload = {
            provider: selectedProvider.code,
            display_name: displayName,
            capabilities,
            is_active: true,
        };
        if (isGcp) payload.topology_mode = onGke ? 'kubernetes' : 'vm';
        if (host) payload.host = host;
        if (username) payload.username = username;
        if (password) payload.password = password;
        if (Object.keys(extra).length > 0) payload.extra_config = extra;
        return payload;
    };

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            await apiClient.post('/integrations/observability/', buildPayload());
            resetState();
            onSaved?.();
            onClose?.();
        } catch (err) {
            const detail = err?.response?.data;
            const message =
                typeof detail === 'string' ? detail
                    : detail?.error || detail?.detail
                    // Serializer field errors — flatten to a readable line
                    || (detail && typeof detail === 'object'
                        ? Object.entries(detail)
                            .map(([field, msgs]) => `${field}: ${Array.isArray(msgs) ? msgs.join(', ') : msgs}`)
                            .join('; ')
                        : null)
                    || t('observabilitySettings.saveFailed');
            setError(message);
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        // We save-then-health-check because the observability
        // health-check endpoint operates on an existing integration.
        // Save first, run health check, surface result; the wizard
        // step advances via polling when computed_state flips.
        setError(null);
        setTestResult(null);
        setTesting(true);
        try {
            const { data: created } = await apiClient.post(
                '/integrations/observability/',
                buildPayload(),
            );
            const { data: health } = await apiClient.post(
                `/integrations/observability/${created.id}/health-check/`,
            );
            const allHealthy = (health?.integrations || []).every((r) => r.healthy);
            setTestResult({
                ok: allHealthy,
                message: allHealthy
                    ? t('observabilityModal.connectionSaved')
                    : ((health.integrations || []).map((r) => r.message).filter(Boolean).join('; ')
                       || t('observabilityModal.healthIssues')),
                savedId: created.id,
            });
            // Regardless of health, the integration is saved and the
            // computed detector will pick it up on the next poll.
            onSaved?.();
        } catch (err) {
            const detail = err?.response?.data;
            const message =
                typeof detail === 'string' ? detail
                    : detail?.error || detail?.detail
                    || (detail && typeof detail === 'object'
                        ? Object.entries(detail)
                            .map(([f, m]) => `${f}: ${Array.isArray(m) ? m.join(', ') : m}`)
                            .join('; ')
                        : null)
                    || t('incidentChannels.testFailed');
            setTestResult({ ok: false, message });
        } finally {
            setTesting(false);
        }
    };

    const handleClose = () => {
        if (saving || testing) return;
        resetState();
        onClose?.();
    };

    return (
        <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
            <DialogTitle>{t('observabilityStep.title')}</DialogTitle>
            <DialogContent dividers>
                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
                )}

                {loadingProviders ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress aria-label={t('onboarding.loading')} />
                    </Box>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="obs-provider-label">{t('globalIntegrations.provider')}</InputLabel>
                            <Select
                                labelId="obs-provider-label"
                                value={providerCode}
                                label={t('globalIntegrations.provider')}
                                onChange={(e) => {
                                    setProviderCode(e.target.value);
                                    setTestResult(null);
                                }}
                            >
                                {/* Promscale was discontinued in 2023 (E6). */}
                                {providers.filter((p) => p.code !== 'promscale').map((p) => {
                                    const supportsLogs = p.capabilities.includes('logs');
                                    return (
                                        <MenuItem
                                            key={p.code}
                                            value={p.code}
                                            disabled={!supportsLogs}
                                        >
                                            {p.name}
                                            {supportsLogs && liveTested(p.code) && ` — ${t('observabilitySettings.liveTestedTitle', { detail: liveTestedDetail(p.code) })}`}
                                            {!supportsLogs && ` ${t('observabilityModal.notLogsSuffix', { kind: notLogsLabel(p.capabilities, t) })}`}
                                        </MenuItem>
                                    );
                                })}
                            </Select>
                            <FormHelperText>{t(LOGS_ONLY_WARNING)}</FormHelperText>
                        </FormControl>

                        {selectedProvider && (
                            <>
                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label={t('observabilityModal.displayName')}
                                    value={displayName}
                                    onChange={(e) => setDisplayName(e.target.value)}
                                    helperText={t('observabilityModal.displayNameHelp')}
                                />

                                <FormControl component="fieldset" sx={{ mb: 2 }}>
                                    <Typography variant="caption" color="text.secondary">
                                        {t('observabilityModal.capabilities')}
                                    </Typography>
                                    <FormGroup row>
                                        {supportsLogs && (
                                            <FormControlLabel
                                                control={
                                                    <Checkbox
                                                        checked={capabilities.includes('logs')}
                                                        onChange={() => toggleCapability('logs')}
                                                    />
                                                }
                                                label={t('observabilitySettings.cap.logs')}
                                            />
                                        )}
                                        {supportsMetrics && (
                                            <FormControlLabel
                                                control={
                                                    <Checkbox
                                                        checked={capabilities.includes('metrics')}
                                                        onChange={() => toggleCapability('metrics')}
                                                    />
                                                }
                                                label={t('observabilitySettings.cap.metrics')}
                                            />
                                        )}
                                    </FormGroup>
                                </FormControl>

                                {isGcp && (
                                    <>
                                        <TextField
                                            fullWidth
                                            sx={{ mb: 2 }}
                                            label={t('observabilitySettings.field.projectId')}
                                            required
                                            value={gcpProject}
                                            onChange={(e) => setGcpProject(e.target.value)}
                                            placeholder="my-project"
                                            helperText={t('observabilityModal.gcpProjectHelp')}
                                        />
                                        <TextField
                                            fullWidth
                                            sx={{ mb: 1 }}
                                            type="password"
                                            label={t('observabilitySettings.field.gcpKey')}
                                            required
                                            value={password}
                                            onChange={(e) => setPassword(e.target.value)}
                                            autoComplete="new-password"
                                            spellCheck={false}
                                            placeholder={t('observabilitySettings.field.gcpKeyPlaceholder')}
                                            helperText={t('observabilityModal.gcpKeyHelp')}
                                        />
                                        <FormControlLabel
                                            sx={{ mb: 2 }}
                                            control={<Checkbox checked={onGke} onChange={(e) => setOnGke(e.target.checked)} />}
                                            label={t('observabilityModal.onGke')}
                                        />
                                    </>
                                )}

                                {!isGcp && <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label={t('observabilitySettings.field.hostUrl')}
                                    value={host}
                                    onChange={(e) => setHost(e.target.value)}
                                    placeholder={HOST_PLACEHOLDERS[providerCode] || 'https://host:port'}
                                    helperText={t('observabilityModal.hostHelp')}
                                />}

                                {isAws && (
                                    <TextField
                                        fullWidth
                                        sx={{ mb: 2 }}
                                        label={t('observabilitySettings.field.awsRegion')}
                                        value={awsRegion}
                                        onChange={(e) => setAwsRegion(e.target.value)}
                                        placeholder="us-east-1"
                                    />
                                )}

                                {(isAws || usesIndexPattern) && (
                                    <TextField
                                        fullWidth
                                        sx={{ mb: 2 }}
                                        label={isAws ? t('observabilityModal.logGroupsOptional') : t('observabilityModal.indexPatternOptional')}
                                        value={logLocation}
                                        onChange={(e) => setLogLocation(e.target.value)}
                                        placeholder={isAws ? '/ecs/shop-api, /aws/lambda/checkout' : 'logs-*, filebeat-*'}
                                        helperText={isAws
                                            ? t('observabilityModal.logGroupsHelp')
                                            : t('observabilityModal.indexPatternHelp')}
                                    />
                                )}

                                {!isGcp && <>
                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label={isAws ? t('observabilitySettings.field.accessKeyId') : t('observabilityModal.usernameOptional')}
                                    required={isAws}
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    autoComplete="off"
                                />

                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    type="password"
                                    label={isAws ? t('observabilitySettings.field.secretAccessKey') : t('observabilityModal.passwordOptional')}
                                    required={isAws}
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                    autoComplete="new-password"
                                    spellCheck={false}
                                />

                                {!isAws && <TextField
                                    fullWidth
                                    sx={{ mb: 1 }}
                                    type="password"
                                    label={t('observabilityModal.apiKeyOptional')}
                                    value={apiKey}
                                    onChange={(e) => setApiKey(e.target.value)}
                                    autoComplete="new-password"
                                    spellCheck={false}
                                    helperText={t('observabilityModal.apiKeyHelp')}
                                />}
                                </>}
                                {providerCode === 'datadog' && <TextField
                                    fullWidth
                                    sx={{ mb: 1 }}
                                    type="password"
                                    label={t('observabilitySettings.field.appKey')}
                                    required
                                    value={appKey}
                                    onChange={(e) => setAppKey(e.target.value)}
                                    autoComplete="new-password"
                                    spellCheck={false}
                                    helperText={t('observabilityModal.appKeyHelp')}
                                />}
                            </>
                        )}

                        {testResult && (
                            <Alert
                                severity={testResult.ok ? 'success' : 'warning'}
                                sx={{ mt: 2 }}
                            >
                                {testResult.message}
                            </Alert>
                        )}
                    </>
                )}
            </DialogContent>
            <DialogActions>
                <Button onClick={handleClose} disabled={saving || testing}>
                    {t('common.cancel')}
                </Button>
                <Button
                    onClick={handleTest}
                    disabled={!canSubmit()}
                    startIcon={testing ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                >
                    {t('observabilityModal.saveAndTest')}
                </Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                >
                    {t('common.save')}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
