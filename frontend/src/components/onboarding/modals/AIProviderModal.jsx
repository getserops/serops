/**
 * AIProviderModal — pick an AI model + supply a key.
 *
 * Security posture:
 *   - API key input uses type=password + autoComplete=new-password so
 *     browser password managers don't autofill or persist it.
 *   - We never log the key (no console.log(formData) even in dev).
 *   - Key is only ever held in component state (unmounted on close)
 *     — never stored in localStorage, never URL-encoded.
 *   - Test-connection sends the key in the POST body only.
 *   - Backend encrypts at rest via Fernet — we send plaintext, once.
 *   - Save calls POST /settings/api-keys/ then PUT /settings/ai/ to
 *     set default_provider. Two-step is unavoidable — those are the
 *     endpoints — but both are same-origin and the state resets
 *     between them so a mid-flow failure never leaves the key
 *     exposed anywhere it wasn't already.
 *
 * Provider list is fetched from /settings/ai/providers/ so it stays
 * in sync with the backend catalog (currently 5 seeded providers).
 * Ollama is keyless — for that provider the modal swaps to a
 * base_url field and does not require a key.
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

// Static hint URLs so we don't have to round-trip to fetch them.
// These are the "Get a key from X" links surfaced next to the API
// key input. Kept in the frontend on purpose — they're presentation
// concerns, not backend data.
const PROVIDER_HINTS = {
    gemini: {
        url: 'https://aistudio.google.com/apikey',
        noteKey: 'aiProviderModal.hint.gemini',
    },
    claude: {
        url: 'https://console.anthropic.com',
        noteKey: 'aiProviderModal.hint.claude',
    },
    deepseek: {
        url: 'https://platform.deepseek.com',
        noteKey: 'aiProviderModal.hint.deepseek',
    },
    openai: {
        url: 'https://platform.openai.com/signup',
        noteKey: 'aiProviderModal.hint.openai',
    },
    ollama: {
        url: 'https://ollama.com/download',
        noteKey: 'aiProviderModal.hint.ollama',
    },
};

export default function AIProviderModal({ open, onClose, onSaved }) {
    const { t } = useTranslation();
    const [providers, setProviders] = useState([]);
    const [providerId, setProviderId] = useState('');
    const [apiKey, setApiKey] = useState('');
    const [baseUrl, setBaseUrl] = useState('');
    const [loadingProviders, setLoadingProviders] = useState(true);
    const [testing, setTesting] = useState(false);
    const [saving, setSaving] = useState(false);
    const [testResult, setTestResult] = useState(null);
    const [error, setError] = useState(null);

    // Clear sensitive state on close/unmount so the key never
    // survives past the modal lifecycle.
    const resetState = () => {
        setProviderId('');
        setApiKey('');
        setBaseUrl('');
        setTestResult(null);
        setError(null);
    };

    useEffect(() => {
        if (!open) return;
        let cancelled = false;
        (async () => {
            setLoadingProviders(true);
            try {
                const { data } = await apiClient.get('/settings/ai/providers/');
                if (!cancelled) {
                    // Filter to active providers only — inactive ones
                    // are catalog entries the admin has disabled.
                    setProviders((data || []).filter((p) => p.is_active));
                    setLoadingProviders(false);
                }
            } catch (err) {
                if (!cancelled) {
                    setError(t('aiProviderModal.loadFailed'));
                    setLoadingProviders(false);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [open, t]);

    // Reset when the modal closes so re-opening starts fresh.
    useEffect(() => {
        if (!open) resetState();
    }, [open]);

    const selectedProvider = providers.find((p) => p.id === providerId);
    const providerName = selectedProvider?.name || '';
    const requiresKey = selectedProvider ? selectedProvider.requires_api_key : true;
    const hint = PROVIDER_HINTS[providerName] || null;

    const canSubmit = () => {
        if (!selectedProvider || saving || testing) return false;
        if (requiresKey && !apiKey.trim()) return false;
        return true;
    };

    const handleTest = async () => {
        setError(null);
        setTestResult(null);
        setTesting(true);
        try {
            const payload = {
                provider_name: providerName,
                // Only send the key when the provider needs one. The Base
                // URL typed here is what gets tested (Ollama on another
                // host used to be tested at localhost).
                ...(requiresKey ? { api_key: apiKey } : {}),
                ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
            };
            const { data } = await apiClient.post('/settings/ai/test/', payload);
            setTestResult({
                ok: !!data.success,
                message: data.message || (data.success ? t('aiProviderModal.connectionSuccessful') : (data.error || t('incidentChannels.testFailed'))),
            });
        } catch (err) {
            setTestResult({
                ok: false,
                message: err?.response?.data?.error || t('aiProviderModal.testRequestFailed'),
            });
        } finally {
            setTesting(false);
        }
    };

    const handleSave = async () => {
        setError(null);
        setSaving(true);
        try {
            if (requiresKey || baseUrl.trim()) {
                // Two-step: (1) save the key and/or Base URL, (2) set the
                // default provider so batch analysis actually uses it.
                // Ollama has no key, but its Base URL must be stored: the
                // wizard used to drop it, and every analysis then called
                // localhost:11434 (journey suite, C3).
                await apiClient.post('/settings/api-keys/', {
                    provider_id: providerId,
                    ...(requiresKey ? { api_key: apiKey } : {}),
                    ...(baseUrl.trim() ? { base_url: baseUrl.trim() } : {}),
                });
            }
            await apiClient.put('/settings/ai/', { default_provider: providerId });
            resetState();
            onSaved?.();
            onClose?.();
        } catch (err) {
            const detail = err?.response?.data;
            const message = typeof detail === 'string'
                ? detail
                : detail?.error || detail?.detail || t('aiProviderModal.saveFailed');
            setError(message);
        } finally {
            setSaving(false);
        }
    };

    const handleClose = () => {
        if (saving || testing) return;
        resetState();
        onClose?.();
    };

    return (
        <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
            <DialogTitle>{t('aiProviderStep.title')}</DialogTitle>
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
                            <InputLabel id="ai-provider-label">{t('globalIntegrations.provider')}</InputLabel>
                            <Select
                                labelId="ai-provider-label"
                                value={providerId}
                                label={t('globalIntegrations.provider')}
                                onChange={(e) => {
                                    setProviderId(e.target.value);
                                    setApiKey('');
                                    setBaseUrl('');
                                    setTestResult(null);
                                }}
                            >
                                {providers.map((p) => (
                                    <MenuItem key={p.id} value={p.id}>
                                        {p.display_name}
                                        {!p.requires_api_key && ` ${t('aiProviderModal.noKeyRequired')}`}
                                    </MenuItem>
                                ))}
                            </Select>
                            <FormHelperText>
                                {t('aiProviderModal.pickHelp')}
                            </FormHelperText>
                        </FormControl>

                        {selectedProvider && requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                type="password"
                                label={t('incidentChannels.apiKey')}
                                value={apiKey}
                                onChange={(e) => setApiKey(e.target.value)}
                                // Prevent password managers from
                                // autofilling an unrelated saved password.
                                autoComplete="new-password"
                                // Spellcheck off is a small privacy win
                                // (some browsers send text to remote
                                // spellcheck services).
                                spellCheck={false}
                                inputProps={{ 'aria-label': t('aiProviderModal.apiKeyAria') }}
                            />
                        )}

                        {selectedProvider && !requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                label={t('globalIntegrations.baseUrl')}
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                placeholder="http://localhost:11434/v1/"
                                helperText={t('aiProviderModal.ollamaBaseUrlHelp')}
                            />
                        )}

                        {selectedProvider && requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                label={t('aiProviderModal.baseUrlOptional')}
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                placeholder={t('aiProviderModal.baseUrlPlaceholder')}
                                helperText={t('aiProviderModal.baseUrlHelp')}
                            />
                        )}

                        {hint && (
                            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
                                {t(hint.noteKey)}{' '}
                                <Link
                                    href={hint.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    underline="hover"
                                >
                                    {requiresKey ? t('aiProviderModal.getKey') : t('aiProviderModal.downloadOllama')}
                                </Link>
                            </Typography>
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
                    disabled={!selectedProvider || testing || saving || (requiresKey && !apiKey.trim())}
                    startIcon={testing ? <CircularProgress aria-label={t('onboarding.loading')} size={16} /> : null}
                >
                    {t('aiProviderModal.testConnection')}
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
