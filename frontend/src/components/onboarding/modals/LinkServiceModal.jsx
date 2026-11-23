/**
 * LinkServiceModal — attach a service to a project.
 *
 * This is the trigger for the aha moment: creating a ProjectService
 * fires the backend's post_save signal which dispatches an immediate
 * batch analysis (see Organisations/signals.py). The wizard's next
 * step (waiting_for_first_analysis) polls until the batch's
 * analyzed_at is set, then flips is_completed.
 *
 * We keep the form minimal — name + service type. SCM/CI-CD linking
 * is a separate step (or post-onboarding Settings). Advanced
 * per-service config lives in the Projects page.
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
    Alert,
    Button,
    CircularProgress,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    FormHelperText,
    InputLabel,
    MenuItem,
    Select,
    TextField,
} from '@mui/material';

import apiClient from '../../../services/api-client';

const SERVICE_TYPES = [
    { code: 'application', labelKey: 'linkServiceModal.type.application' },
    { code: 'infrastructure', labelKey: 'linkServiceModal.type.infrastructure' },
    { code: 'custom', labelKey: 'linkServiceModal.type.custom' },
];

export default function LinkServiceModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
    const [projects, setProjects] = useState([]);
    const [projectId, setProjectId] = useState('');
    const [name, setName] = useState('');
    const [serviceType, setServiceType] = useState('application');
    const [loadingProjects, setLoadingProjects] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const resetState = () => {
        setProjectId('');
        setName('');
        setServiceType('application');
        setError(null);
    };

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        (async () => {
            setLoadingProjects(true);
            try {
                const { data } = await apiClient.get('/projects/');
                if (!cancelled) {
                    const list = Array.isArray(data) ? data : (data?.results || []);
                    setProjects(list);
                    // Auto-select if only one project — reduces friction.
                    if (list.length === 1) setProjectId(list[0].id);
                    setLoadingProjects(false);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(t('linkServiceModal.loadFailed'));
                    setLoadingProjects(false);
                }
            }
        })();
        return () => { cancelled = true; };
    }, [open, t]);

    useEffect(() => {
        if (!open) resetState();
    }, [open]);

    const canSubmit = () => projectId && name.trim().length > 0 && !saving;

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            await apiClient.post(`/projects/${projectId}/services/`, {
                name: name.trim(),
                service_type: serviceType,
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
                    || t('linkServiceModal.saveFailed');
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
        <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs">
            <DialogTitle>{t('linkServiceStep.title')}</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                {loadingProjects ? (
                    <CircularProgress aria-label={t('onboarding.loading')} sx={{ mx: 'auto', display: 'block', my: 3 }} />
                ) : projects.length === 0 ? (
                    <Alert severity="warning">
                        {t('linkServiceModal.noProjects')}
                    </Alert>
                ) : (
                    <>
                        <FormControl fullWidth sx={{ mb: 2 }}>
                            <InputLabel id="ls-project-label">{t('globalIntegrations.project')}</InputLabel>
                            <Select
                                labelId="ls-project-label"
                                value={projectId}
                                label={t('globalIntegrations.project')}
                                onChange={(e) => setProjectId(e.target.value)}
                            >
                                {projects.map((p) => (
                                    <MenuItem key={p.id} value={p.id}>
                                        {p.name}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>

                        <TextField
                            fullWidth
                            autoFocus
                            sx={{ mb: 2 }}
                            label={t('linkServiceModal.serviceName')}
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            inputProps={{ maxLength: 255 }}
                            helperText={t('linkServiceModal.serviceNameHelp')}
                        />

                        <FormControl fullWidth>
                            <InputLabel id="ls-type-label">{t('linkServiceModal.serviceType')}</InputLabel>
                            <Select
                                labelId="ls-type-label"
                                value={serviceType}
                                label={t('linkServiceModal.serviceType')}
                                onChange={(e) => setServiceType(e.target.value)}
                            >
                                {SERVICE_TYPES.map((st) => (
                                    <MenuItem key={st.code} value={st.code}>
                                        {t(st.labelKey)}
                                    </MenuItem>
                                ))}
                            </Select>
                            <FormHelperText>
                                {t('linkServiceModal.serviceTypeHelp')}
                            </FormHelperText>
                        </FormControl>
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
                    {t('linkServiceStep.link')}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
