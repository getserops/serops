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
import { useTranslation } from 'react-i18next';
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

// Integration types a CI/CD binding accepts (ProviderIntegration.provider_type,
// as CICDBindingSerializer.validate checks it). This listed the Pipeline
// choices (github_actions, bitbucket_pipelines), so GitHub and Bitbucket
// integrations were never offered.
const CICD_PROVIDER_TYPES = new Set([
    'gitlab',
    'github',
    'jenkins',
    'azure_devops',
    'bitbucket',
    'argocd',
    'flux',
]);

const BINDING_TYPES = [
    { code: 'build', labelKey: 'cicdModal.bindingType.build' },
    { code: 'deploy', labelKey: 'cicdModal.bindingType.deploy' },
    { code: 'test', labelKey: 'cicdModal.bindingType.test' },
    { code: 'release', labelKey: 'cicdModal.bindingType.release' },
];

export default function CICDModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
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
                            label: `${p.name} → ${s.name || s.subtype || t('scmModal.serviceFallback')}`,
                        });
                    });
                });
                setServices(flat);

                if (flat.length === 1) setServiceId(flat[0].id);
                if (allIntegrations.length === 1) setIntegrationId(allIntegrations[0].id);

                setLoadingLists(false);
            } catch (err) {
                if (!cancelled) {
                    setError(t('scmModal.loadFailed'));
                    setLoadingLists(false);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [open, t]);

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
                    || t('cicdModal.saveFailed');
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
            <DialogTitle>{t('cicdModal.title')}</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                {loadingLists ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress aria-label={t('onboarding.loading')} />
                    </Box>
                ) : !hasIntegrations ? (
                    <Alert severity="info">
                        {t('cicdModal.noIntegrationsBefore')}{' '}
                        <Link
                            href="/dash/settings/integrations"
                            underline="hover"
                        >
                            {t('scmModal.settingsIntegrations')}
                        </Link>
                        {t('cicdModal.noIntegrationsAfter')}
                    </Alert>
                ) : !hasServices ? (
                    <Alert severity="warning">
                        {t('scmModal.noServices')}
                    </Alert>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="cicd-integration-label">{t('addService.integration')}</InputLabel>
                            <Select
                                labelId="cicd-integration-label"
                                value={integrationId}
                                label={t('addService.integration')}
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
                            <InputLabel id="cicd-service-label">{t('services.service')}</InputLabel>
                            <Select
                                labelId="cicd-service-label"
                                value={serviceId}
                                label={t('services.service')}
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
                            <InputLabel id="cicd-type-label">{t('cicdModal.purpose')}</InputLabel>
                            <Select
                                labelId="cicd-type-label"
                                value={bindingType}
                                label={t('cicdModal.purpose')}
                                onChange={(e) => setBindingType(e.target.value)}
                            >
                                {BINDING_TYPES.map((b) => (
                                    <MenuItem key={b.code} value={b.code}>
                                        {t(b.labelKey)}
                                    </MenuItem>
                                ))}
                            </Select>
                            <FormHelperText>
                                {t('cicdModal.purposeHelp')}
                            </FormHelperText>
                        </FormControl>

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label={t('cicdModal.pipelineId')}
                            value={pipelineId}
                            onChange={(e) => setPipelineId(e.target.value)}
                            placeholder={t('cicdModal.pipelineIdPlaceholder')}
                            helperText={t('cicdModal.pipelineIdHelp')}
                        />

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label={t('cicdModal.pipelineNameOptional')}
                            value={pipelineName}
                            onChange={(e) => setPipelineName(e.target.value)}
                        />

                        <TextField
                            fullWidth
                            label={t('cicdModal.pipelineUrlOptional')}
                            value={pipelineUrl}
                            onChange={(e) => setPipelineUrl(e.target.value)}
                            placeholder={t('cicdModal.pipelineUrlPlaceholder')}
                        />

                        <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 2 }}>
                            {t('cicdModal.footnote')}
                        </Typography>
                    </>
                )}
            </DialogContent>
            <DialogActions>
                <Button onClick={handleClose} disabled={saving}>{t('common.cancel')}</Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                >
                    {t('cicdStep.link')}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
