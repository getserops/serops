/**
 * AI Settings Component
 * Configure AI model providers with full API key management
 */


import React, { useState, useEffect } from 'react';
import { Form, Button, Spinner, Badge, Modal, InputGroup } from 'react-bootstrap';
import {
    FaRobot, FaCheck, FaTimes, FaKey, FaPlay,
    FaEye, FaEyeSlash, FaPlus, FaTrash, FaShieldAlt,
    FaExclamationTriangle, FaBolt
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import SettingsService from '../../services/settings.service';
import CollapsibleSection from './CollapsibleSection';
import AIBudgetCard from './AIBudgetCard';
import './SettingsLayout.css';

const AISettings = () => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState({});
    const [providers, setProviders] = useState([]);
    const [settings, setSettings] = useState({
        default_provider: null,
        fallback_provider: null,
        use_custom_keys: false
    });
    const [apiKeys, setApiKeys] = useState([]);

    // API Key input states
    const [keyInputs, setKeyInputs] = useState({});
    const [urlInputs, setUrlInputs] = useState({});
    const [showKeys, setShowKeys] = useState({});
    const [savingKey, setSavingKey] = useState({});
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [deleteProvider, setDeleteProvider] = useState(null);

    // Provider Management State
    const [showProviderModal, setShowProviderModal] = useState(false);
    const [editingProvider, setEditingProvider] = useState(null);
    const [providerForm, setProviderForm] = useState({
        name: '',
        display_name: '',
        adapter_class: 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
        api_base_url: '',
        default_model: '',
        is_active: true
    });

    useEffect(() => {
        if (editingProvider) {
            setProviderForm({
                name: editingProvider.name,
                display_name: editingProvider.display_name,
                adapter_class: editingProvider.adapter_class,
                api_base_url: editingProvider.api_base_url || '',
                default_model: editingProvider.default_model || '',
                is_active: editingProvider.is_active
            });
        } else {
            setProviderForm({
                name: '',
                display_name: '',
                adapter_class: 'ai_model.adapters.openai_generic.GenericOpenAIAdapter',
                api_base_url: '',
                default_model: '',
                is_active: true
            });
        }
    }, [editingProvider]);

    const handleSaveProvider = async () => {
        try {
            setSaving(true);
            if (editingProvider) {
                await SettingsService.updateAIProvider(editingProvider.id, providerForm);
                toast.success('Provider updated');
            } else {
                await SettingsService.createAIProvider(providerForm);
                toast.success('Provider created');
            }
            setShowProviderModal(false);
            fetchData(); // Refresh list
        } catch (error) {
            toast.error(error.response?.data?.error || 'Failed to save provider');
        } finally {
            setSaving(false);
        }
    };

    const handleSaveProviderWrapper = async (providerData) => {
        try {
            await SettingsService.updateAIProvider(providerData.id, providerData);
            toast.success('Status updated');
            fetchData();
        } catch (error) {
            toast.error('Failed to update status');
        }
    };

    const handleDeleteProvider = async (id) => {
        try {
            await SettingsService.deleteAIProvider(id);
            toast.success('Provider deleted');
            fetchData();
        } catch (error) {
            toast.error('Failed to delete provider');
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const fetchData = async () => {
        try {
            setLoading(true);
            const [providersData, settingsData, keysData] = await Promise.all([
                SettingsService.getAIProviders(),
                SettingsService.getAISettings(),
                SettingsService.getAPIKeys()
            ]);
            setProviders(providersData);
            setSettings(settingsData);
            setApiKeys(keysData);

            // Initialize key inputs
            const inputs = {};
            keysData.forEach(key => {
                inputs[key.provider_name] = '';
            });
            setKeyInputs(inputs);
        } catch (error) {
            toast.error(t('ai.loadFailed'));
        } finally {
            setLoading(false);
        }
    };

    const handleProviderChange = (field, value) => {
        setSettings(prev => ({ ...prev, [field]: value ? parseInt(value) : null }));
    };

    const handleSave = async () => {
        try {
            setSaving(true);
            await SettingsService.updateAISettings(settings);
            toast.success(t('ai.saveSuccess'));
        } catch (error) {
            toast.error(error.response?.data?.error || t('ai.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const handleKeyInputChange = (providerName, value) => {
        setKeyInputs(prev => ({ ...prev, [providerName]: value }));
    };

    const handleUrlInputChange = (providerName, value) => {
        setUrlInputs(prev => ({ ...prev, [providerName]: value }));
    };

    const handleSaveApiKey = async (provider) => {
        const keyValue = keyInputs[provider.name];
        if (!keyValue || !keyValue.trim()) {
            toast.warning(t('ai.enterApiKey'));
            return;
        }

        try {
            setSavingKey(prev => ({ ...prev, [provider.name]: true }));
            const baseUrl = urlInputs[provider.name] || null;
            await SettingsService.saveAPIKey(provider.id, keyValue.trim(), baseUrl);
            toast.success(t('ai.keySaved', { provider: provider.display_name }));

            setKeyInputs(prev => ({ ...prev, [provider.name]: '' }));
            setUrlInputs(prev => ({ ...prev, [provider.name]: '' }));
            const keysData = await SettingsService.getAPIKeys();
            setApiKeys(keysData);
        } catch (error) {
            toast.error(error.response?.data?.error || t('ai.keySaveFailed'));
        } finally {
            setSavingKey(prev => ({ ...prev, [provider.name]: false }));
        }
    };

    const handleDeleteApiKey = async () => {
        if (!deleteProvider) return;

        try {
            await SettingsService.deleteAPIKey(deleteProvider.id);
            toast.success(t('ai.keyDeleted', { provider: deleteProvider.display_name }));
            setShowDeleteModal(false);
            setDeleteProvider(null);

            const keysData = await SettingsService.getAPIKeys();
            setApiKeys(keysData);
        } catch (error) {
            toast.error(error.response?.data?.error || t('ai.keyDeleteFailed'));
        }
    };

    const handleTestConnection = async (providerName) => {
        try {
            setTesting(prev => ({ ...prev, [providerName]: true }));
            const result = await SettingsService.testAIConnection(providerName);
            if (result.success) {
                toast.success(result.message);
                const keysData = await SettingsService.getAPIKeys();
                setApiKeys(keysData);
            } else {
                toast.error(result.error || t('ai.testFailed'));
            }
        } catch (error) {
            toast.error(error.response?.data?.error || t('ai.testFailed'));
        } finally {
            setTesting(prev => ({ ...prev, [providerName]: false }));
        }
    };

    const toggleShowKey = (providerName) => {
        setShowKeys(prev => ({ ...prev, [providerName]: !prev[providerName] }));
    };

    const getProviderIcon = (name) => {
        const icons = {
            gemini: <FaBolt />,
            deepseek: <FaRobot />,
            claude: <FaShieldAlt />,
            openai: <FaRobot />
        };
        return icons[name] || <FaRobot />;
    };

    const getExistingKey = (providerName) => {
        return apiKeys.find(k => k.provider_name === providerName);
    };

    const getApiKeyStatus = (providerName) => {
        const key = getExistingKey(providerName);
        if (!key) return { badge: null, hasKey: false };

        let badge;
        if (key.last_test_success === true) {
            badge = <Badge bg="success" className="d-flex align-items-center gap-1"><FaCheck size={10} /> {t('ai.connected')}</Badge>;
        } else if (key.last_test_success === false) {
            badge = <Badge bg="danger" className="d-flex align-items-center gap-1"><FaTimes size={10} /> {t('ai.failed')}</Badge>;
        } else {
            badge = <Badge bg="secondary">{t('ai.notTested')}</Badge>;
        }

        return { badge, hasKey: true, maskedKey: key.masked_key, baseUrl: key.base_url };
    };

    const isProviderSupported = (provider) => {
        return provider.is_active;
    };

    if (loading) {
        return (
            <div className="text-center py-5">
                <Spinner animation="border" variant="primary" />
                <p className="mt-3 text-muted">{t('ai.loading')}</p>
            </div>
        );
    }

    const activeProviders = providers.filter(p => p.is_active);

    return (
        <div className="settings-section">
            <div className="settings-header">
                <div className="settings-icon-wrapper ai">
                    <FaRobot />
                </div>
                <div>
                    <h2>{t('ai.title')}</h2>
                    <p>{t('ai.subtitle')}</p>
                </div>
            </div>

            {/* Monthly cost budget — shown first because admins want to
                see current spend + set caps BEFORE picking providers.
                Uses OrganisationAISettings.monthly_budget_usd (Batch 26). */}
            <AIBudgetCard />

            {/* Default Provider Selection */}
            <CollapsibleSection
                title={t('ai.primaryProvider')}
                description={t('ai.primaryProviderDesc')}
                defaultExpanded={true}
            >
                <div className="settings-selection-grid">
                    {activeProviders.map((provider) => {
                        const supported = isProviderSupported(provider);
                        return (
                            <div
                                key={provider.id}
                                className={`settings-selection-card ${settings.default_provider === provider.id ? 'active' : ''} ${!supported ? 'opacity-50' : ''}`}
                                onClick={() => supported && handleProviderChange('default_provider', provider.id)}
                                style={{ cursor: supported ? 'pointer' : 'not-allowed' }}
                            >
                                <div className="settings-selection-icon" style={{ fontSize: '2rem' }}>
                                    {getProviderIcon(provider.name)}
                                </div>
                                <span className="settings-selection-label">
                                    {provider.display_name}
                                </span>
                                <span className="settings-selection-desc">
                                    {provider.default_model}
                                </span>
                                {!supported && <Badge bg="warning" text="dark" className="mt-2">{t('ai.comingSoon')}</Badge>}
                            </div>
                        );
                    })}
                </div>
            </CollapsibleSection>



            {/* Manage AI Providers (Consolidated) */}
            <CollapsibleSection
                title={t('ai.manageProviders') || "Manage AI Providers"}
                description={t('ai.manageProvidersDesc') || "Configure all AI providers, including API keys, endpoints, and adapters."}
            >
                <div className="d-flex justify-content-end mb-3">
                    <Button variant="outline-primary" size="sm" onClick={() => { setEditingProvider(null); setShowProviderModal(true); }}>
                        <FaPlus className="me-1" /> {t('ai.addProvider') || "Add Provider"}
                    </Button>
                </div>

                <div className="table-responsive">
                    <table className="table settings-table">
                        <thead>
                            <tr>
                                <th style={{ width: '25%' }}>Provider</th>
                                <th style={{ width: '15%' }}>Status</th>
                                <th style={{ width: '40%' }}>Configuration (API Key & URL)</th>
                                <th style={{ width: '20%' }}>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {providers.map(provider => {
                                const keyStatus = getApiKeyStatus(provider.name);
                                const isKeyVisible = showKeys[provider.name];
                                const isSavingKey = savingKey[provider.name];
                                const inputValue = keyInputs[provider.name] || '';

                                return (
                                    <tr key={provider.id} style={{ verticalAlign: 'top' }}>
                                        <td>
                                            <div className="d-flex align-items-center gap-2 mb-1">
                                                <span style={{ fontSize: '1.2rem' }}>{getProviderIcon(provider.name)}</span>
                                                <span className="fw-semibold">{provider.display_name}</span>
                                            </div>
                                            <div className="small text-muted">{provider.adapter_class?.split('.').pop()}</div>
                                            <div className="small text-muted">{provider.default_model}</div>
                                        </td>
                                        <td>
                                            <div className="d-flex flex-column gap-2">
                                                {provider.is_active ?
                                                    <Badge bg="success" className="align-self-start">Active</Badge> :
                                                    <Badge bg="secondary" className="align-self-start">Inactive</Badge>
                                                }
                                                {keyStatus.badge && <div className="mt-1">{keyStatus.badge}</div>}
                                            </div>
                                        </td>
                                        <td>
                                            {/* Inline Key Configuration */}
                                            <div className="d-flex flex-column gap-2">
                                                {/* URL Input */}
                                                <InputGroup size="sm">
                                                    <InputGroup.Text id={`url-addon-${provider.id}`} style={{ width: '60px' }}>URL</InputGroup.Text>
                                                    <Form.Control
                                                        type="text"
                                                        placeholder={t('ai.baseUrlPlaceholder', { example: '' })}
                                                        value={urlInputs[provider.name] !== undefined ? urlInputs[provider.name] : (provider.api_base_url || '')}
                                                        onChange={(e) => handleUrlInputChange(provider.name, e.target.value)}
                                                    />
                                                </InputGroup>

                                                {/* Key Input */}
                                                <InputGroup size="sm">
                                                    <InputGroup.Text id={`key-addon-${provider.id}`} style={{ width: '60px' }}>Key</InputGroup.Text>
                                                    <Form.Control
                                                        type={isKeyVisible ? 'text' : 'password'}
                                                        placeholder={keyStatus.hasKey ? '••••••••' : t('ai.enterApiKey')}
                                                        value={inputValue}
                                                        onChange={(e) => handleKeyInputChange(provider.name, e.target.value)}
                                                    />
                                                    <Button variant="outline-secondary" onClick={() => toggleShowKey(provider.name)}
                                                            aria-label={isKeyVisible ? t('ai.hideKey') : t('ai.showKey')}>
                                                        {isKeyVisible ? <FaEyeSlash /> : <FaEye />}
                                                    </Button>
                                                    <Button
                                                        variant="primary"
                                                        onClick={() => handleSaveApiKey(provider)}
                                                        disabled={isSavingKey || (!inputValue && !urlInputs[provider.name])}
                                                        aria-label={t('ai.saveKey')}
                                                    >
                                                        {isSavingKey ? <Spinner size="sm" animation="border" /> : <FaCheck />}
                                                    </Button>
                                                </InputGroup>

                                                {keyStatus.hasKey && (
                                                    <div className="d-flex justify-content-between align-items-center small mt-1">
                                                        <span className="text-muted text-truncate" style={{ maxWidth: '200px' }}>
                                                            Key: <code>{keyStatus.maskedKey}</code>
                                                        </span>
                                                        <div className="d-flex gap-2">
                                                            <span
                                                                className="text-primary cursor-pointer"
                                                                style={{ cursor: 'pointer' }}
                                                                onClick={() => handleTestConnection(provider.name)}
                                                            >
                                                                {testing[provider.name] ? 'Testing...' : 'Test Connection'}
                                                            </span>
                                                            <span
                                                                className="text-danger cursor-pointer"
                                                                style={{ cursor: 'pointer' }}
                                                                onClick={() => { setDeleteProvider(provider); setShowDeleteModal(true); }}
                                                            >
                                                                Delete Key
                                                            </span>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </td>
                                        <td>
                                            <div className="d-flex gap-2">
                                                <Button variant="outline-secondary" size="sm" onClick={() => { setEditingProvider(provider); setShowProviderModal(true); }}>
                                                    Edit Config
                                                </Button>

                                                {!provider.is_system && (
                                                    <Button variant="outline-danger" size="sm" onClick={() => {
                                                        if (confirm('Are you sure you want to delete this provider?')) {
                                                            handleDeleteProvider(provider.id);
                                                        }
                                                    }}>
                                                        <FaTrash />
                                                    </Button>
                                                )}
                                            </div>
                                        </td>
                                    </tr>
                                )
                            })}
                        </tbody>
                    </table>
                </div>
            </CollapsibleSection>

            {/* Save Button */}
            <div className="d-flex justify-content-end mt-4">
                <button
                    className="settings-save-btn text-white"
                    onClick={handleSave}
                    disabled={saving}
                >
                    {saving ? t('ai.saving') : t('ai.saveSettings')}
                </button>
            </div>

            {/* Delete Confirmation Modal */}
            <Modal show={showDeleteModal} onHide={() => setShowDeleteModal(false)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>{t('ai.deleteApiKey')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>
                        {t('ai.deleteConfirm', { provider: deleteProvider?.display_name })}
                    </p>
                    <div className="alert alert-warning small">
                        {t('ai.deleteWarning')}
                    </div>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowDeleteModal(false)}>
                        {t('common.cancel')}
                    </Button>
                    <Button variant="danger" onClick={handleDeleteApiKey}>
                        {t('ai.deleteKey')}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Provider Add/Edit Modal */}
            <Modal show={showProviderModal} onHide={() => setShowProviderModal(false)} centered size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>{editingProvider ? "Edit Provider" : "Add New Provider"}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form>
                        <div className="row">
                            <div className="col-md-6 mb-3">
                                <Form.Label>Internal Name (ID)</Form.Label>
                                <Form.Control
                                    type="text"
                                    value={providerForm.name}
                                    onChange={e => setProviderForm({ ...providerForm, name: e.target.value.toLowerCase().replace(/\s+/g, '_') })}
                                    disabled={editingProvider}
                                    placeholder="e.g. ollama_local"
                                />
                                <Form.Text className="text-muted">Unique identifier.</Form.Text>
                            </div>
                            <div className="col-md-6 mb-3">
                                <Form.Label>Display Name</Form.Label>
                                <Form.Control
                                    type="text"
                                    value={providerForm.display_name}
                                    onChange={e => setProviderForm({ ...providerForm, display_name: e.target.value })}
                                    placeholder="e.g. Local Ollama"
                                />
                            </div>
                        </div>

                        <div className="mb-3">
                            <Form.Label>Adapter Type</Form.Label>
                            <Form.Select
                                value={providerForm.adapter_class}
                                onChange={e => setProviderForm({ ...providerForm, adapter_class: e.target.value })}
                            >
                                <option value="ai_model.adapters.openai_generic.GenericOpenAIAdapter">OpenAI Compatible (Mistral, Ollama, DeepSeek)</option>
                                <option value="ai_model.adapters.gemini.GeminiAdapter">Google Gemini</option>
                                <option value="ai_model.adapters.claude.ClaudeAdapter">Anthropic Claude</option>
                            </Form.Select>
                            <Form.Text className="text-muted">Select "OpenAI Compatible" for most self-hosted models.</Form.Text>
                        </div>

                        <div className="mb-3">
                            <Form.Label>API Base URL</Form.Label>
                            <Form.Control
                                type="text"
                                value={providerForm.api_base_url}
                                onChange={e => setProviderForm({ ...providerForm, api_base_url: e.target.value })}
                                placeholder="http://localhost:11434/v1"
                            />
                        </div>

                        <div className="mb-3">
                            <Form.Label>Default Model Name</Form.Label>
                            <Form.Control
                                type="text"
                                value={providerForm.default_model}
                                onChange={e => setProviderForm({ ...providerForm, default_model: e.target.value })}
                                placeholder="e.g. llama3"
                            />
                        </div>

                        <Form.Check
                            type="checkbox"
                            label="Active"
                            checked={providerForm.is_active}
                            onChange={e => setProviderForm({ ...providerForm, is_active: e.target.checked })}
                        />
                    </Form>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowProviderModal(false)}>Close</Button>
                    <Button variant="primary" onClick={handleSaveProvider} disabled={saving}>
                        {saving ? 'Saving...' : 'Save Provider'}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default AISettings;

