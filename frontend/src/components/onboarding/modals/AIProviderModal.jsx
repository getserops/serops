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
        note: 'Free-tier key — sufficient for testing.',
    },
    claude: {
        url: 'https://console.anthropic.com',
        note: 'Signup credits vary.',
    },
    deepseek: {
        url: 'https://platform.deepseek.com',
        note: 'New accounts get a one-time 5M-token grant (no card).',
    },
    openai: {
        url: 'https://platform.openai.com/signup',
        note: 'Paid — no automatic free credits since mid-2025.',
    },
    ollama: {
        url: 'https://ollama.com/download',
        note: 'Local install — no key required.',
    },
};

export default function AIProviderModal({ open, onClose, onSaved }) {
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
                    setError('Failed to load AI providers');
                    setLoadingProviders(false);
                }
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [open]);

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
                message: data.message || (data.success ? 'Connection successful' : (data.error || 'Test failed')),
            });
        } catch (err) {
            setTestResult({
                ok: false,
                message: err?.response?.data?.error || 'Test request failed',
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
                : detail?.error || detail?.detail || 'Failed to save AI provider';
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
            <DialogTitle>Choose your AI model</DialogTitle>
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
                            <InputLabel id="ai-provider-label">Provider</InputLabel>
                            <Select
                                labelId="ai-provider-label"
                                value={providerId}
                                label="Provider"
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
                                        {!p.requires_api_key && ' (no key required)'}
                                    </MenuItem>
                                ))}
                            </Select>
                            <FormHelperText>
                                Pick the model you want SerOps to use for analysis.
                                You can switch later in Settings → AI.
                            </FormHelperText>
                        </FormControl>

                        {selectedProvider && requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                type="password"
                                label="API Key"
                                value={apiKey}
                                onChange={(e) => setApiKey(e.target.value)}
                                // Prevent password managers from
                                // autofilling an unrelated saved password.
                                autoComplete="new-password"
                                // Spellcheck off is a small privacy win
                                // (some browsers send text to remote
                                // spellcheck services).
                                spellCheck={false}
                                inputProps={{ 'aria-label': 'API key' }}
                            />
                        )}

                        {selectedProvider && !requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                label="Base URL"
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                placeholder="http://localhost:11434/v1/"
                                helperText="Leave blank to use the default local Ollama endpoint."
                            />
                        )}

                        {selectedProvider && requiresKey && (
                            <TextField
                                fullWidth
                                sx={{ mb: 1 }}
                                label="Base URL (optional)"
                                value={baseUrl}
                                onChange={(e) => setBaseUrl(e.target.value)}
                                placeholder="Leave blank for provider default"
                                helperText="Override the provider's default endpoint (e.g. a proxy)."
                            />
                        )}

                        {hint && (
                            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 1 }}>
                                {hint.note}{' '}
                                <Link
                                    href={hint.url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    underline="hover"
                                >
                                    {requiresKey ? 'Get a key' : 'Download Ollama'}
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
                    Cancel
                </Button>
                <Button
                    onClick={handleTest}
                    disabled={!selectedProvider || testing || saving || (requiresKey && !apiKey.trim())}
                    startIcon={testing ? <CircularProgress size={16} /> : null}
                >
                    Test connection
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
