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
                    || 'Failed to create project';
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
            <DialogTitle>Create your first project</DialogTitle>
            <DialogContent dividers>
                {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

                <TextField
                    fullWidth
                    autoFocus
                    sx={{ mb: 2 }}
                    label="Project name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    // Trim on blur is user-friendly but we also trim on
                    // submit — server also validates.
                    inputProps={{ maxLength: 255 }}
                    helperText="e.g. Payments Backend, Ingestion Pipeline"
                />

                <TextField
                    fullWidth
                    multiline
                    rows={2}
                    label="Description (optional)"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    inputProps={{ maxLength: 500 }}
                />
            </DialogContent>
            <DialogActions>
                <Button onClick={handleClose} disabled={saving}>Cancel</Button>
                <Button
                    variant="contained"
                    onClick={handleSave}
                    disabled={!canSubmit()}
                    startIcon={saving ? <CircularProgress size={16} /> : null}
                >
                    Create project
                </Button>
            </DialogActions>
        </Dialog>
    );
}
