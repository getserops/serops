/**
 * CreateProjectModal — minimum viable project creation.
 *
 * Backend auto-generates default environments if we don't pass any,
 * so this modal only asks for the essentials (name + optional
 * description). Advanced environment configuration lives in the
 * Settings page — the wizard's goal is fastest TTV, not surfacing
 * every option.
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
    TextField,
} from '@mui/material';

import apiClient from '../../../services/api-client';

export default function CreateProjectModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);

    const resetState = () => {
        setName('');
        setDescription('');
        setError(null);
    };

    useEffect(() => {
        if (!open) resetState();
    }, [open]);

    const canSubmit = () => name.trim().length > 0 && !saving;

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            await apiClient.post('/projects/', {
                name: name.trim(),
                ...(description.trim() ? { description: description.trim() } : {}),
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
                    || t('createProjectModal.saveFailed');
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
            <DialogTitle>{t('createProjectStep.title')}</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                <TextField
                    fullWidth
                    autoFocus
                    sx={{ mb: 2 }}
                    label={t('createProjectModal.projectName')}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    // Trim on blur is user-friendly but we also trim on
                    // submit — server also validates.
                    inputProps={{ maxLength: 255 }}
                    helperText={t('createProjectModal.projectNameHelp')}
                />

                <TextField
                    fullWidth
                    multiline
                    rows={2}
                    label={t('createProjectModal.descriptionOptional')}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    inputProps={{ maxLength: 500 }}
                />
            </DialogContent>
            <DialogActions>
                <Button onClick={handleClose} disabled={saving}>{t('common.cancel')}</Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                >
                    {t('createProjectStep.create')}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
