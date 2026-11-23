/**
 * StepConnectRepo - Step 2a: Connect to code repository
 * For Application service type - select SCM provider and repository
 */

import React, { useState, useEffect } from "react";
import { Form, Spinner, Alert } from "react-bootstrap";
import { FaGitlab, FaGithub, FaBitbucket, FaCheck, FaExclamationTriangle } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import { IntegrationService } from "../../../services/integration.service";

const scmProviders = [
    { id: "gitlab", name: "GitLab", icon: FaGitlab, color: "#FC6D26" },
    { id: "github", name: "GitHub", icon: FaGithub, color: "#24292F" },
    { id: "bitbucket", name: "Bitbucket", icon: FaBitbucket, color: "#0052CC" },
];

const StepConnectRepo = ({
    formData,
    updateFormData,
    integrations,
    onVerify,
    verifying,
    verified,
    verificationMessage
}) => {
    const { t } = useTranslation();
    const [repos, setRepos] = useState([]);
    const [loadingRepos, setLoadingRepos] = useState(false);
    const [repoError, setRepoError] = useState(null);

    // Filter integrations for selected provider
    const providerIntegrations = integrations.filter(
        i => i.provider_type === formData.scmProvider && i.is_active
    );

    // Auto-select if only one integration
    useEffect(() => {
        if (providerIntegrations.length === 1 && !formData.integrationId) {
            updateFormData({ integrationId: providerIntegrations[0].id });
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [providerIntegrations.length, formData.integrationId]);

    // Fetch repos when integration selected
    useEffect(() => {
        if (formData.integrationId) {
            fetchRepos(formData.integrationId);
        }
    }, [formData.integrationId]);

    const fetchRepos = async (integrationId) => {
        setLoadingRepos(true);
        setRepoError(null);
        try {
            const data = await IntegrationService.getRepos(integrationId);
            // Handle different response formats
            if (Array.isArray(data)) {
                setRepos(data);
            } else if (data && Array.isArray(data.results)) {
                // Handle paginated response
                setRepos(data.results);
            } else if (data && Array.isArray(data.repositories)) {
                setRepos(data.repositories);
            } else {
                console.warn("Unexpected repos response format:", data);
                setRepos([]);
            }
        } catch (error) {
            console.error("Failed to fetch repos:", error);
            setRepoError(t('addServiceWizard.connectRepo.fetchFailed'));
            setRepos([]);
        } finally {
            setLoadingRepos(false);
        }
    };

    const handleRepoSelect = (repoId, repoName) => {
        // Extract just the repo name (last part after /) for service name
        const shortName = repoName.includes('/')
            ? repoName.split('/').pop()
            : repoName;

        updateFormData({
            repositoryId: repoId,
            repositoryName: repoName,
            serviceName: shortName // Use short name for service
        });
        // Auto-verify on selection
        if (onVerify) {
            onVerify();
        }
    };

    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">{t('addServiceWizard.connectRepo.title')}</h5>
            <p className="wizard-step-subtitle">
                {t('addServiceWizard.connectRepo.subtitle')}
            </p>

            {/* An application whose code is elsewhere (or deployed by Argo CD,
                Flux or Jenkins only) can be added without a repository, as in
                the onboarding wizard (journey suite, B4). */}
            <Form.Check
                type="switch"
                role="switch"
                id="wizard-no-repo"
                className="mb-3"
                label={t('addServiceWizard.connectRepo.noRepo')}
                checked={!!formData.noRepo}
                onChange={(e) => updateFormData({
                    noRepo: e.target.checked, integrationId: null, repositoryId: null, repositoryName: '',
                })}
            />

            {formData.noRepo && (
                <div className="wizard-form-section">
                    <label className="wizard-form-label" htmlFor="wizard-no-repo-name">{t('addServiceWizard.serviceNameRequired')}</label>
                    <Form.Control id="wizard-no-repo-name"
                        type="text"
                        placeholder="payments"
                        value={formData.serviceName || ""}
                        onChange={(e) => updateFormData({ serviceName: e.target.value })}
                        className="rounded-3"
                    />
                    <Form.Text className="text-muted">
                        {t('addServiceWizard.connectRepo.noRepoHelp')}
                    </Form.Text>
                </div>
            )}

            {!formData.noRepo && (<>
            {/* Provider Selection */}
            <div className="wizard-form-section">
                <span className="wizard-form-label d-block" id="wizard-scm-provider">{t('addServiceWizard.connectRepo.provider')}</span>
                <div className="provider-buttons" role="group" aria-labelledby="wizard-scm-provider">
                    {scmProviders.map((provider) => {
                        const Icon = provider.icon;
                        const isActive = formData.scmProvider === provider.id;

                        return (
                            <button
                                key={provider.id}
                                type="button"
                                aria-pressed={isActive}
                                className={`provider-btn ${isActive ? 'active' : ''}`}
                                onClick={() => updateFormData({
                                    scmProvider: provider.id,
                                    integrationId: null,
                                    repositoryId: null,
                                    repositoryName: ''
                                })}
                                style={isActive ? { background: provider.color, borderColor: provider.color } : {}}
                            >
                                <Icon className="me-2" />
                                {provider.name}
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Integration Selection */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-connectrepo-1">{t('addService.integration')}</label>
                {providerIntegrations.length === 0 ? (
                    <Alert variant="warning" className="d-flex align-items-center">
                        <FaExclamationTriangle className="me-2" />
                        {t('addServiceWizard.noIntegrations', { provider: formData.scmProvider })}
                        <a href="/dash/settings/integrations" className="ms-1">{t('addServiceWizard.addOneInSettings')}</a>
                    </Alert>
                ) : (
                    <Form.Select id="wizard-connectrepo-1"
                        value={formData.integrationId || ""}
                        onChange={(e) => updateFormData({
                            integrationId: parseInt(e.target.value),
                            repositoryId: null,
                            repositoryName: ''
                        })}
                        className="rounded-3"
                    >
                        <option value="">{t('serviceForms.selectIntegration')}</option>
                        {providerIntegrations.map(integration => (
                            <option key={integration.id} value={integration.id}>
                                {integration.name}
                            </option>
                        ))}
                    </Form.Select>
                )}
            </div>

            {/* Repository Selection */}
            {formData.integrationId && (
                <div className="wizard-form-section">
                    <label className="wizard-form-label" htmlFor="wizard-connectrepo-2">{t('serviceForms.repository')}</label>
                    {loadingRepos ? (
                        <div className="d-flex align-items-center text-muted">
                            <Spinner size="sm" className="me-2" />
                            {t('addServiceWizard.connectRepo.loadingRepos')}
                        </div>
                    ) : repoError ? (
                        <Alert variant="danger">{repoError}</Alert>
                    ) : repos.length > 0 ? (
                        <Form.Select id="wizard-connectrepo-2"
                            value={formData.repositoryId || ""}
                            onChange={(e) => {
                                const val = e.target.value;
                                const repo = repos.find(r =>
                                    String(r.id) === val || r.full_name === val
                                );
                                if (repo) {
                                    handleRepoSelect(
                                        repo.id || repo.full_name,
                                        repo.full_name || repo.name || repo.path_with_namespace
                                    );
                                }
                            }}
                            className="rounded-3"
                        >
                            <option value="">{t('addServiceWizard.connectRepo.selectRepo')}</option>
                            {repos.map(repo => (
                                <option
                                    key={repo.id || repo.full_name}
                                    value={repo.id || repo.full_name}
                                >
                                    {repo.full_name || repo.name || repo.path_with_namespace}
                                </option>
                            ))}
                        </Form.Select>
                    ) : (
                        <Form.Control
                            type="text"
                            placeholder={t('addServiceWizard.connectRepo.repoPlaceholder')}
                            value={formData.repositoryId || ""}
                            onChange={(e) => updateFormData({
                                repositoryId: e.target.value,
                                repositoryName: e.target.value
                            })}
                            className="rounded-3"
                        />
                    )}
                </div>
            )}

            {/* Service Name */}
            {formData.repositoryId && (
                <div className="wizard-form-section">
                    <label className="wizard-form-label" htmlFor="wizard-connectrepo-3">{t('addServiceWizard.connectRepo.serviceNameOptional')}</label>
                    <Form.Control id="wizard-connectrepo-3"
                        type="text"
                        placeholder={t('addServiceWizard.connectRepo.serviceNamePlaceholder')}
                        value={formData.serviceName || ""}
                        onChange={(e) => updateFormData({ serviceName: e.target.value })}
                        className="rounded-3"
                    />
                    <Form.Text className="text-muted">
                        {t('addServiceWizard.connectRepo.serviceNameHelp')}
                    </Form.Text>
                </div>
            )}

            </>)}

            {/* Verification Status */}
            {formData.repositoryId && !formData.noRepo && (
                <div className="wizard-form-section">
                    {verifying ? (
                        <div className="verification-badge loading">
                            <Spinner size="sm" /> {t('addServiceWizard.connectRepo.verifying')}
                        </div>
                    ) : verified ? (
                        <div className="verification-badge success">
                            <FaCheck /> {t('addServiceWizard.connectRepo.verified')}
                        </div>
                    ) : verificationMessage ? (
                        <div className="verification-badge error">
                            <FaExclamationTriangle /> {verificationMessage}
                        </div>
                    ) : null}
                </div>
            )}
        </div>
    );
};

export default StepConnectRepo;
