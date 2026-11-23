/**
 * SCMModal — link a service to a source-control repository.
 *
 * SCM binding is optional in the wizard; a "Skip for now" button on
 * the step lets the user defer this. If they proceed, we require:
 *   - An existing SCM ProviderIntegration in Settings (github,
 *     gitlab, bitbucket, azure_devops — either `category='scm'` or
 *     the unified `category='devops'`).
 *   - A ProjectService to bind the repo to.
 *   - A repository ID (owner/repo, GitLab project ID, etc.).
 *
 * If the user has no SCM integration configured yet, we show an
 * inline notice with a deep link to Settings → Integrations. That's
 * honest UX — inlining OAuth/PAT setup for four providers plus
 * their edge cases would blow up the wizard.
 *
 * Security posture:
 *   - No credential fields on this modal — the API tokens live on
 *     the ProviderIntegration and are set in Settings.
 *   - Repository ID / URL are user-supplied strings surfaced back
 *     to the user; JSX auto-escapes so no XSS risk.
 *   - Backend serializer validates the integration belongs to the
 *     org and matches an SCM provider_type — cannot bind to an
 *     arbitrary integration ID.
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

// Providers whose ProviderIntegration.provider_type maps to SCM.
// Matches the backend SCM_PROVIDER_CHOICES in providers/models.py.
const SCM_PROVIDER_TYPES = new Set(['gitlab', 'github', 'bitbucket', 'azure_devops']);

export default function SCMModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
    const [integrations, setIntegrations] = useState([]);
    const [services, setServices] = useState([]);
    const [integrationId, setIntegrationId] = useState('');
    const [serviceId, setServiceId] = useState('');
    const [repoId, setRepoId] = useState('');
    const [repoName, setRepoName] = useState('');
    const [defaultBranch, setDefaultBranch] = useState('main');
    const [loadingLists, setLoadingLists] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const resetState = () => {
        setIntegrationId('');
        setServiceId('');
        setRepoId('');
        setRepoName('');
        setDefaultBranch('main');
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

                // Backend list endpoint returns either an array or a
                // paginated {results: []} — handle both defensively.
                const allIntegrations = Array.isArray(integrationsRes.data)
                    ? integrationsRes.data
                    : integrationsRes.data?.results || [];
                setIntegrations(
                    allIntegrations.filter(
                        (i) => SCM_PROVIDER_TYPES.has(i.provider_type)
                            && (i.category === 'scm' || i.category === 'devops')
                    )
                );

                // Flatten services out of each project so the picker
                // shows "Project → Service" pairs.
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

                // Auto-select if only one — reduces friction.
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

    const isAzure = integrations.find((i) => String(i.id) === String(integrationId))?.provider_type === 'azure_devops';
    const canSubmit = () =>
        hasIntegrations && hasServices && integrationId && serviceId
        && repoId.trim().length > 0 && !saving;

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            await apiClient.post('/projects/scm-bindings/', {
                project_service: serviceId,
                integration: integrationId,
                repository_id: repoId.trim(),
                ...(repoName.trim() ? { repository_name: repoName.trim() } : {}),
                ...(defaultBranch.trim() ? { default_branch: defaultBranch.trim() } : {}),
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
                    || t('scmModal.saveFailed');
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
            <DialogTitle>{t('scmModal.title')}</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                {loadingLists ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 3 }}>
                        <CircularProgress aria-label={t('onboarding.loading')} />
                    </Box>
                ) : !hasIntegrations ? (
                    <Alert severity="info">
                        {t('scmModal.noIntegrationsBefore')}{' '}
                        <Link
                            href="/dash/settings/integrations"
                            underline="hover"
                        >
                            {t('scmModal.settingsIntegrations')}
                        </Link>
                        {t('scmModal.noIntegrationsAfter')}
                    </Alert>
                ) : !hasServices ? (
                    <Alert severity="warning">
                        {t('scmModal.noServices')}
                    </Alert>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="scm-integration-label">{t('addService.integration')}</InputLabel>
                            <Select
                                labelId="scm-integration-label"
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
                            <InputLabel id="scm-service-label">{t('services.service')}</InputLabel>
                            <Select
                                labelId="scm-service-label"
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

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label={t('scmModal.repoId')}
                            value={repoId}
                            onChange={(e) => setRepoId(e.target.value)}
                            placeholder={isAzure ? 'organization/project/repository' : t('scmModal.repoIdPlaceholder')}
                            helperText={isAzure
                                ? t('scmModal.repoIdHelpAzure')
                                : t('scmModal.repoIdHelp')}
                        />

                        <TextField
                            fullWidth
                            sx={{ mb: 2 }}
                            label={t('scmModal.repoNameOptional')}
                            value={repoName}
                            onChange={(e) => setRepoName(e.target.value)}
                            helperText={t('scmModal.repoNameHelp')}
                        />

                        <TextField
                            fullWidth
                            label={t('scmModal.defaultBranch')}
                            value={defaultBranch}
                            onChange={(e) => setDefaultBranch(e.target.value)}
                        />

                        <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 2 }}>
                            {t('scmModal.footnote')}
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
                    {t('scmStep.link')}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
