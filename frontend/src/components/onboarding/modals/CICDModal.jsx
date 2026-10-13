/**
 * CICDModal — link a service to a CI/CD pipeline.
 *
 * Same "requires existing integration" pattern as SCMModal — if the
 * user has no CI/CD ProviderIntegration configured yet, we point them
 * at Settings → Integrations. CI/CD binding is optional in the
 * wizard; a "Skip for now" button on the step lets users defer.
 *
 * Unlike SCM, a ProjectService can have MULTIPLE CICDBindings (one
 * for build, one for deploy, etc.), so no OneToOne violation to
 * worry about.
 *
 * Security posture: identical to SCMModal — no credential fields;
 * the API token / webhook secret lives on the ProviderIntegration.
 * Pipeline ID / URL are user-supplied strings surfaced back via
 * JSX (auto-escaped).
 */

import React, { useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    FormHelperText,
    InputLabel,
    Link,
    MenuItem,
    Select,
    TextField,
    Typography,
} from '@mui/material';

import apiClient from '../../../services/api-client';

// Providers whose provider_type maps to CI/CD. Matches
// CICD_PROVIDER_CHOICES in providers/models.py.
const CICD_PROVIDER_TYPES = new Set([
    'gitlab',
    'github_actions',
    'jenkins',
    'azure_devops',
    'bitbucket_pipelines',
]);

const BINDING_TYPES = [
    { code: 'build', label: 'Build pipeline' },
    { code: 'deploy', label: 'Deployment pipeline' },
    { code: 'test', label: 'Test pipeline' },
    { code: 'release', label: 'Release pipeline' },
];

export default function CICDModal({ open, onClose, onSaved }) {
    const [integrations, setIntegrations] = useState([]);
    const [services, setServices] = useState([]);
    const [integrationId, setIntegrationId] = useState('');
    const [serviceId, setServiceId] = useState('');
    const [bindingType, setBindingType] = useState('build');
    const [pipelineId, setPipelineId] = useState('');
    const [pipelineName, setPipelineName] = useState('');
    const [pipelineUrl, setPipelineUrl] = useState('');
    const [loadingLists, setLoadingLists] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const resetState = () => {
        setIntegrationId('');
        setServiceId('');
        setBindingType('build');
        setPipelineId('');
        setPipelineName('');
        setPipelineUrl('');
        setError(null);
    };

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        (async () => {
            setLoadingLists(true);
            try {
                const [integrationsRes, projectsRes] = await Promise.all([
                    apiClient.get('/providers/integrations/'),
                    apiClient.get('/projects/'),
                ]);
                if (cancelled) return;

                const allIntegrations = Array.isArray(integrationsRes.data)
                    ? integrationsRes.data
                    : integrationsRes.data?.results || [];
                setIntegrations(
                    allIntegrations.filter(
                        (i) => CICD_PROVIDER_TYPES.has(i.provider_type)
                            && (i.category === 'cicd' || i.category === 'devops')
                    )
                );

                const projects = Array.isArray(projectsRes.data)
                    ? projectsRes.data
                    : projectsRes.data?.results || [];
                const flat = [];
                projects.forEach((p) => {
                    (p.services || []).forEach((s) => {
                        flat.push({
                            id: s.id,
                            label: `${p.name} → ${s.name || s.subtype || 'service'}`,
                        });
                    });
                });
                setServices(flat);

                if (flat.length === 1) setServiceId(flat[0].id);
                if (allIntegrations.length === 1) setIntegrationId(allIntegrations[0].id);

                setLoadingLists(false);
            } catch (err) {
                if (!cancelled) {
                    setError('Failed to load integrations or services');
                    setLoadingLists(false);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [open]);

    useEffect(() => {
        if (!open) resetState();
    }, [open]);

    const hasIntegrations = integrations.length > 0;
    const hasServices = services.length > 0;

    const canSubmit = () =>
        hasIntegrations && hasServices && integrationId && serviceId
        && bindingType && pipelineId.trim().length > 0 && !saving;

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            await apiClient.post('/projects/cicd-bindings/', {
                project_service: serviceId,
                integration: integrationId,
                binding_type: bindingType,
                pipeline_id: pipelineId.trim(),
                ...(pipelineName.trim() ? { pipeline_name: pipelineName.trim() } : {}),
                ...(pipelineUrl.trim() ? { pipeline_url: pipelineUrl.trim() } : {}),
            });
            resetState();
            onSaved?.();
            onClose?.();
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
                    || 'Failed to save CI/CD binding';
            setError(message);
        } finally {
            setSaving(false);
        }
    };

    const handleClose = () => {
        if (saving) return;
        resetState();
        onClose?.();
    };

    return (
        <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
            <DialogTitle>Link a CI/CD pipeline</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                {loadingLists ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress />
                    </Box>
                ) : !hasIntegrations ? (
                    <Alert severity="info">
                        You don't have any CI/CD provider integrations yet.
                        Add one under{' '}
                        <Link
                            href="/dash/settings/integrations"
                            underline="hover"
                        >
                            Settings → Integrations
                        </Link>
                        , then come back to link a pipeline to your service.
                    </Alert>
                ) : !hasServices ? (
                    <Alert severity="warning">
                        No services found. Complete the "Link a service"
                        step first.
                    </Alert>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="cicd-integration-label">Integration</InputLabel>
                            <Select
                                labelId="cicd-integration-label"
                                value={integrationId}
                                label="Integration"
                                onChange={(e) => setIntegrationId(e.target.value)}
                            >
                                {integrations.map((i) => (
                                    <MenuItem key={i.id} value={i.id}>
                                        {i.name} — {i.provider_type}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="cicd-service-label">Service</InputLabel>
                            <Select
                                labelId="cicd-service-label"
                                value={serviceId}
                                label="Service"
                                onChange={(e) => setServiceId(e.target.value)}
                            >
                                {services.map((s) => (
                                    <MenuItem key={s.id} value={s.id}>
                                        {s.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="cicd-type-label">Pipeline purpose</InputLabel>
                            <Select
                                labelId="cicd-type-label"
                                value={bindingType}
                                label="Pipeline purpose"
                                onChange={(e) => setBindingType(e.target.value)}
                            >
                                {BINDING_TYPES.map((t) => (
                                    <MenuItem key={t.code} value={t.code}>
                                        {t.label}
                                    </MenuItem>
                                ))}
                            </Select>
                            <FormHelperText>
                                A service can have multiple pipelines (build + deploy, etc.)
                            </FormHelperText>
                        </FormControl>

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label="Pipeline ID"
                            value={pipelineId}
                            onChange={(e) => setPipelineId(e.target.value)}
                            placeholder="e.g. numeric job ID, or GitHub workflow file path"
                            helperText="Provider-specific identifier for the pipeline."
                        />

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label="Pipeline name (optional)"
                            value={pipelineName}
                            onChange={(e) => setPipelineName(e.target.value)}
                        />

                        <TextField
                            fullWidth
                            label="Pipeline URL (optional)"
                            value={pipelineUrl}
                            onChange={(e) => setPipelineUrl(e.target.value)}
                            placeholder="Link users click to jump to the pipeline"
                        />

                        <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 2 }}>
                            AI will correlate incidents on the linked service
                            with recent builds / deploys from this pipeline.
                        </Typography>
                    </>
                )}
            </DialogContent>
            <DialogActions>
                <Button onClick={handleClose} disabled={saving}>Cancel</Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress size={16} /> : null}
                >
                    Link pipeline
                </Button>
            </DialogActions>
        </Dialog>
    );
}
