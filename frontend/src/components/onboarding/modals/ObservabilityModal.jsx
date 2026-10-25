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
const notLogsLabel = (caps) => (caps.includes('metrics') ? 'metrics only' : 'traces only');

const LOGS_ONLY_WARNING =
    "SerOps needs at least one logs-capable source to run AI analysis. " +
    "You can add metric-only sources later for correlation.";

export default function ObservabilityModal({ open, onClose, onSaved }) {
    const [providers, setProviders] = useState([]);
    const [providerCode, setProviderCode] = useState('');
    const [displayName, setDisplayName] = useState('');
    const [capabilities, setCapabilities] = useState([]);
    const [host, setHost] = useState('');
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [apiKey, setApiKey] = useState('');
    const [awsRegion, setAwsRegion] = useState('');
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
        setAwsRegion('');
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
                    setError('Failed to load observability providers');
                    setLoadingProviders(false);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [open]);

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
        return true;
    };

    const buildPayload = () => {
        const extra = {};
        if (apiKey && !isAws) extra.api_key = apiKey;
        if (isAws && awsRegion.trim()) extra.aws_region = awsRegion.trim();
        const payload = {
            provider: selectedProvider.code,
            display_name: displayName,
            capabilities,
            is_active: true,
        };
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
                    || 'Failed to save integration';
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
                    ? 'Connection successful — integration saved.'
                    : ((health.integrations || []).map((r) => r.message).filter(Boolean).join('; ')
                       || 'Health check reported issues.'),
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
                    || 'Test failed';
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
            <DialogTitle>Connect an observability source</DialogTitle>
            <DialogContent dividers>
                {error && (
                    <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
                )}

                {loadingProviders ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress />
                    </Box>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="obs-provider-label">Provider</InputLabel>
                            <Select
                                labelId="obs-provider-label"
                                value={providerCode}
                                label="Provider"
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
                                            {!supportsLogs && ` (${notLogsLabel(p.capabilities)}: add it later in Settings → Integrations)`}
                                        </MenuItem>
                                    );
                                })}
                            </Select>
                            <FormHelperText>{LOGS_ONLY_WARNING}</FormHelperText>
                        </FormControl>

                        {selectedProvider && (
                            <>
                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label="Display name"
                                    value={displayName}
                                    onChange={(e) => setDisplayName(e.target.value)}
                                    helperText="Shown wherever this integration is referenced."
                                />

                                <FormControl component="fieldset" sx={{ mb: 2 }}>
                                    <Typography variant="caption" color="text.secondary">
                                        Capabilities
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
                                                label="Logs"
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
                                                label="Metrics"
                                            />
                                        )}
                                    </FormGroup>
                                </FormControl>

                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label="Host URL"
                                    value={host}
                                    onChange={(e) => setHost(e.target.value)}
                                    placeholder={HOST_PLACEHOLDERS[providerCode] || 'https://host:port'}
                                    helperText="Provider endpoint. Not needed for AWS, Google Cloud or Azure."
                                />

                                {isAws && (
                                    <TextField
                                        fullWidth
                                        sx={{ mb: 2 }}
                                        label="AWS Region"
                                        value={awsRegion}
                                        onChange={(e) => setAwsRegion(e.target.value)}
                                        placeholder="us-east-1"
                                    />
                                )}

                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    label={isAws ? 'Access Key ID' : 'Username (optional)'}
                                    required={isAws}
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                    autoComplete="off"
                                />

                                <TextField
                                    fullWidth
                                    sx={{ mb: 2 }}
                                    type="password"
                                    label={isAws ? 'Secret Access Key' : 'Password (optional)'}
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
                                    label="API Key (optional)"
                                    value={apiKey}
                                    onChange={(e) => setApiKey(e.target.value)}
                                    autoComplete="new-password"
                                    spellCheck={false}
                                    helperText="Only some providers use API keys (Datadog, cloud services)."
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
                    Cancel
                </Button>
                <Button
                    onClick={handleTest}
                    disabled={!canSubmit()}
                    startIcon={testing ? <CircularProgress size={16} /> : null}
                >
                    Save &amp; test
                </Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress size={16} /> : null}
                >
                    Save
                </Button>
            </DialogActions>
        </Dialog>
    );
}
