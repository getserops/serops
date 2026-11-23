/**
 * Service form components for AddServiceModal
 * Each form handles a specific service type's input fields
 * 
 * Shared Components:
 * - RepoSelector: Dropdown to select repository from integration
 * - IntegrationPrompt: Alert shown when no integrations configured
 * - IntegrationSelector: Toggle + dropdown for global integration
 */

import React from "react";
import { Form, Alert, Button, Row, Col, Spinner } from "react-bootstrap";
import { FaSync, FaPlug, FaExternalLinkAlt, FaCogs, FaInfoCircle } from "react-icons/fa";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { IntegrationService } from "../../services/integration.service";

/**
 * Provider display names for UI
 */
const PROVIDER_NAMES = {
    gitlab: "GitLab",
    github: "GitHub",
    bitbucket: "Bitbucket",
    azure_devops: "Azure DevOps",
    jenkins: "Jenkins",
};

/**
 * IntegrationPrompt - Shown when no integrations are configured for a provider
 * Guides users to Settings to add an integration
 */
const IntegrationPrompt = ({ providerType }) => {
    const { t } = useTranslation();
    const providerName = PROVIDER_NAMES[providerType] || providerType;

    return (
        <Alert variant="info" className="mb-3 d-flex align-items-center gap-2">
            <FaPlug className="flex-shrink-0" />
            <div className="flex-grow-1">
                <strong>{t('serviceForms.noIntegration', { provider: providerName })}</strong>
                <p className="mb-0 small">
                    {t('serviceForms.connectGlobalHint')}
                </p>
            </div>
            <Link
                to="/dash/settings/integrations"
                className="btn btn-sm btn-outline-primary d-flex align-items-center gap-1"
            >
                <span>{t('globalIntegrations.addIntegration')}</span>
                <FaExternalLinkAlt size={10} />
            </Link>
        </Alert>
    );
};

/**
 * IntegrationSelector - Toggle + dropdown for selecting a global integration
 * Provides consistent UX across all provider forms
 */
const IntegrationSelector = ({
    integrations,
    formData,
    handleChange,
    providerType,
    switchId
}) => {
    const { t } = useTranslation();
    const hasIntegrations = integrations && integrations.length > 0;
    const [useIntegration, setUseIntegration] = React.useState(hasIntegrations);
    const providerName = PROVIDER_NAMES[providerType] || providerType;

    React.useEffect(() => {
        if (hasIntegrations && !formData.integration_id && useIntegration) {
            handleChange({ target: { name: 'integration_id', value: integrations[0].id } });
        }
    }, [hasIntegrations, useIntegration, integrations, formData.integration_id, handleChange]);

    const handleModeSwitch = (e) => {
        setUseIntegration(e.target.checked);
        if (!e.target.checked) {
            handleChange({ target: { name: 'integration_id', value: '' } });
        } else if (hasIntegrations) {
            handleChange({ target: { name: 'integration_id', value: integrations[0].id } });
        }
    };

    // No integrations configured - show prompt
    if (!hasIntegrations) {
        return <IntegrationPrompt providerType={providerType} />;
    }

    return (
        <div className="mb-3 p-3 bg-light rounded border">
            <Form.Check
                type="switch"
                id={switchId}
                label={t('serviceForms.useGlobalIntegration', { provider: providerName })}
                checked={useIntegration}
                onChange={handleModeSwitch}
                className="mb-2 fw-bold"
            />
            {useIntegration && (
                <Form.Select
                    name="integration_id"
                    value={formData.integration_id}
                    onChange={handleChange}
                >
                    {integrations.map(int => (
                        <option key={int.id} value={int.id}>{int.name}</option>
                    ))}
                </Form.Select>
            )}
        </div>
    );
};

// Export shared state hook for forms that need it
const useIntegrationMode = (integrations, formData, handleChange) => {
    const hasIntegrations = integrations && integrations.length > 0;
    const [useIntegration, setUseIntegration] = React.useState(hasIntegrations);

    React.useEffect(() => {
        if (hasIntegrations && !formData.integration_id && useIntegration) {
            handleChange({ target: { name: 'integration_id', value: integrations[0].id } });
        }
    }, [hasIntegrations, useIntegration, integrations, formData.integration_id, handleChange]);

    const handleModeSwitch = (checked) => {
        setUseIntegration(checked);
        if (!checked) {
            handleChange({ target: { name: 'integration_id', value: '' } });
        } else if (hasIntegrations) {
            handleChange({ target: { name: 'integration_id', value: integrations[0].id } });
        }
    };

    return { hasIntegrations, useIntegration, handleModeSwitch };
};

/**
 * RepoSelector - Dropdown to select repository from an integration
 * Fetches repos dynamically and handles loading/error states
 */
const RepoSelector = ({ integrationId, value, onChange, placeholder }) => {
    const { t } = useTranslation();
    const [repos, setRepos] = React.useState([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState(null);

    React.useEffect(() => {
        if (integrationId) {
            fetchRepos();
        } else {
            setRepos([]);
        }
    }, [integrationId]);

    const fetchRepos = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await IntegrationService.getRepos(integrationId);
            if (Array.isArray(data)) {
                setRepos(data);
            } else if (data && Array.isArray(data.results)) {
                // Handle paginated response
                setRepos(data.results);
            } else {
                console.warn("Unexpected repos response format:", data);
                setRepos([]);
            }
        } catch (err) {
            console.error("Failed to load repos:", err);
            setError(t('serviceForms.loadReposFailed'));
            setRepos([]);
        } finally {
            setLoading(false);
        }
    };

    const safeRepos = Array.isArray(repos) ? repos : [];

    return (
        <Form.Group className="mb-3">
            <Form.Label>
                {t('serviceForms.selectRepository')} <span className="text-danger">*</span>
            </Form.Label>
            <div className="d-flex gap-2">
                <Form.Select
                    value={safeRepos.some(r => String(r.id) === String(value) || r.full_name === value) ? value : ""}
                    onChange={(e) => {
                        const val = e.target.value;
                        const repo = safeRepos.find(r => String(r.id) === val || r.full_name === val);
                        if (repo) onChange(repo);
                    }}
                    disabled={loading || !safeRepos.length}
                    isInvalid={!!error}
                >
                    <option value="">
                        {loading ? t('common.loading') : error ? t('serviceForms.loadReposError') : placeholder}
                    </option>
                    {safeRepos.map(repo => (
                        <option key={repo.id || repo.full_name} value={repo.id || repo.full_name}>
                            {repo.full_name || repo.name}
                        </option>
                    ))}
                </Form.Select>
                <Button
                    variant="outline-secondary"
                    onClick={fetchRepos}
                    disabled={loading}
                    title={t('serviceForms.refreshRepositories')}
                >
                    {loading ? <Spinner size="sm" animation="border" /> : <FaSync />}
                </Button>
            </div>
            {error && <Form.Text className="text-danger">{error}</Form.Text>}
        </Form.Group>
    );
};

/**
 * CustomServiceForm - Form for creating a custom service
 */
export const CustomServiceForm = ({ formData, handleChange }) => {
    const { t } = useTranslation();
    return (
    <div className="custom-service-form">
        <Form.Group className="mb-3">
            <Form.Label>
                {t('addService.serviceName')} <span className="text-danger">*</span>
            </Form.Label>
            <Form.Control
                type="text"
                name="name"
                placeholder={t('addService.serviceNamePlaceholder')}
                value={formData.name}
                onChange={handleChange}
                className="rounded-3"
                required
            />
        </Form.Group>

        <Form.Group className="mb-3">
            <Form.Label>{t('addService.description')}</Form.Label>
            <Form.Control
                as="textarea"
                rows={4}
                name="description"
                placeholder={t('serviceForms.descriptionPlaceholder')}
                value={formData.description}
                onChange={handleChange}
                className="rounded-3"
                maxLength={500}
            />
            <div className="text-muted small text-end mt-1">
                {(formData.description || '').length}/500
            </div>
        </Form.Group>
    </div>
    );
};

/**
 * InfrastructureForm - Form for infrastructure services (database, cache, queue)
 */
export const InfrastructureForm = ({ formData, handleChange }) => {
    const { t } = useTranslation();
    return (
    <div className="infrastructure-service-form">
        <Form.Group className="mb-3">
            <Form.Label>
                {t('addService.serviceName')} <span className="text-danger">*</span>
            </Form.Label>
            <Form.Control
                type="text"
                name="name"
                placeholder={t('serviceForms.namePlaceholderDatabase')}
                value={formData.name}
                onChange={handleChange}
                className="rounded-3"
                required
            />
        </Form.Group>

        <Row>
            <Col md={8}>
                <Form.Group className="mb-3">
                    <Form.Label>
                        {t('serviceForms.host')} <span className="text-muted">{t('common.optional')}</span>
                    </Form.Label>
                    <Form.Control
                        type="text"
                        name="host"
                        placeholder={t('serviceForms.hostPlaceholder')}
                        value={formData.host}
                        onChange={handleChange}
                        className="rounded-3"
                    />
                </Form.Group>
            </Col>
            <Col md={4}>
                <Form.Group className="mb-3">
                    <Form.Label>{t('serviceForms.port')}</Form.Label>
                    <Form.Control
                        type="text"
                        name="port"
                        placeholder="5432"
                        value={formData.port}
                        onChange={handleChange}
                        className="rounded-3"
                    />
                </Form.Group>
            </Col>
        </Row>

        <Form.Group className="mb-3">
            <Form.Label>{t('serviceForms.healthCheckUrl')}</Form.Label>
            <Form.Control
                type="text"
                name="health_check_url"
                placeholder={t('serviceForms.healthCheckPlaceholder')}
                value={formData.health_check_url}
                onChange={handleChange}
                className="rounded-3"
            />
        </Form.Group>
    </div>
    );
};

/**
 * GitLabForm - Form for GitLab integration with verification
 */
export const GitLabForm = ({
    formData,
    handleChange,
    verifyGitLabProject,
    verifying,
    projectVerified,
    verificationMessage,
    integrations = []
}) => {
    const { t } = useTranslation();
    const { hasIntegrations, useIntegration, handleModeSwitch } = useIntegrationMode(
        integrations, formData, handleChange
    );

    return (
        <div className="gitlab-service-form">
            {/* Integration Selector - shows prompt if no integrations */}
            {hasIntegrations ? (
                <div className="mb-3 p-3 bg-light rounded border">
                    <Form.Check
                        type="switch"
                        id="use-gitlab-int"
                        label={t('serviceForms.useGlobalIntegration', { provider: 'GitLab' })}
                        checked={useIntegration}
                        onChange={(e) => handleModeSwitch(e.target.checked)}
                        className="mb-2 fw-bold"
                    />
                    {useIntegration && (
                        <Form.Select
                            name="integration_id"
                            value={formData.integration_id}
                            onChange={handleChange}
                        >
                            {integrations.map(int => (
                                <option key={int.id} value={int.id}>{int.name}</option>
                            ))}
                        </Form.Select>
                    )}
                </div>
            ) : (
                <IntegrationPrompt providerType="gitlab" />
            )}

            {useIntegration && (
                <RepoSelector
                    integrationId={formData.integration_id}
                    value={formData.project_id}
                    onChange={(repo) => {
                        handleChange({ target: { name: 'project_id', value: repo.id } });
                        if (!formData.name) handleChange({ target: { name: 'name', value: repo.name } });
                        handleChange({ target: { name: 'gitlab_url', value: repo.url } });
                    }}
                    placeholder={t('serviceForms.selectGitlabProject')}
                />
            )}

            {!useIntegration && (
                <Form.Group className="mb-3">
                    <Form.Label>{t('services.gitlabUrl')} <span className="text-danger">*</span></Form.Label>
                    <Form.Control type="url" name="gitlab_url" placeholder="https://gitlab.com" value={formData.gitlab_url} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                </Form.Group>
            )}

            <Form.Group className="mb-3">
                <Form.Label>{t('services.projectId')} <span className="text-danger">*</span></Form.Label>
                <Form.Control type="text" name="project_id" placeholder={t('serviceForms.gitlabProjectIdPlaceholder')} value={formData.project_id} onChange={handleChange} className="rounded-3" required />
                <Form.Text className="text-muted">{t('serviceForms.gitlabProjectIdHelp')}</Form.Text>
            </Form.Group>

            <Form.Group className="mb-3">
                <Form.Label>{t('addService.serviceName')}</Form.Label>
                <Form.Control type="text" name="name" placeholder={t('serviceForms.gitlabNamePlaceholder')} value={formData.name} onChange={handleChange} className="rounded-3" />
                <Form.Text className="text-muted">{t('serviceForms.gitlabNameHelp')}</Form.Text>
            </Form.Group>

            {!useIntegration && (
                <Form.Group className="mb-3">
                    <Form.Label>{t('globalIntegrations.accessToken')} <span className="text-danger">*</span></Form.Label>
                    <Form.Control type="password" name="access_token" placeholder={t('serviceForms.gitlabTokenPlaceholder')} value={formData.access_token} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                    <Form.Text className="text-muted">{t('serviceForms.gitlabTokenHelp')}</Form.Text>
                </Form.Group>
            )}

            {/* Verification Section */}
            <div className="border rounded-3 p-3 mb-3 bg-light">
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{t('serviceForms.verifyConnection', { provider: 'GitLab' })}</strong>
                        <p className="text-muted small mb-0">
                            {t('serviceForms.verifyHint')}
                        </p>
                    </div>
                    <Button
                        variant={projectVerified ? "success" : "outline-primary"}
                        size="sm"
                        onClick={verifyGitLabProject}
                        disabled={verifying || !formData.project_id || (!useIntegration && !formData.access_token)}
                    >
                        {verifying ? (
                            <>
                                <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                                {t('serviceForms.verifying')}
                            </>
                        ) : projectVerified ? (
                            <>✓ {t('serviceForms.verifiedLabel')}</>
                        ) : (
                            t('serviceForms.verify')
                        )}
                    </Button>
                </div>
                {verificationMessage && (
                    <Alert
                        variant={projectVerified ? "success" : "warning"}
                        className="mt-2 mb-0 py-2"
                    >
                        {verificationMessage}
                    </Alert>
                )}
            </div>
        </div>
    );
};

/**
 * GitHubForm - Form for GitHub integration with verification
 */
export const GitHubForm = ({
    formData,
    handleChange,
    verifyGitHubProject,
    verifying,
    projectVerified,
    verificationMessage,
    integrations = []
}) => {
    const { t } = useTranslation();
    const { hasIntegrations, useIntegration, handleModeSwitch } = useIntegrationMode(
        integrations, formData, handleChange
    );

    return (
        <div className="github-service-form">
            {/* Integration Selector - shows prompt if no integrations */}
            {hasIntegrations ? (
                <div className="mb-3 p-3 bg-light rounded border">
                    <Form.Check
                        type="switch"
                        id="use-github-integration"
                        label={t('serviceForms.useGlobalIntegration', { provider: 'GitHub' })}
                        checked={useIntegration}
                        onChange={(e) => handleModeSwitch(e.target.checked)}
                        className="mb-2 fw-bold"
                    />
                    {useIntegration && (
                        <Form.Select
                            name="integration_id"
                            value={formData.integration_id}
                            onChange={handleChange}
                        >
                            {integrations.map(int => (
                                <option key={int.id} value={int.id}>{int.name}</option>
                            ))}
                        </Form.Select>
                    )}
                </div>
            ) : (
                <IntegrationPrompt providerType="github" />
            )}

            {useIntegration && (
                <RepoSelector
                    integrationId={formData.integration_id}
                    value={formData.github_repo}
                    onChange={(repo) => {
                        handleChange({ target: { name: 'github_repo', value: repo.full_name } });
                        if (!formData.name) handleChange({ target: { name: 'name', value: repo.name } });
                    }}
                    placeholder={t('serviceForms.selectRepoPlaceholder', { provider: 'GitHub' })}
                />
            )}

            <Form.Group className="mb-3">
                <Form.Label>
                    {t('serviceForms.repository')} <span className="text-danger">*</span>
                </Form.Label>
                <Form.Control
                    type="text"
                    name="github_repo"
                    placeholder="owner/repository-name"
                    value={formData.github_repo}
                    onChange={handleChange}
                    className="rounded-3"
                    required
                />
                <Form.Text className="text-muted">
                    {t('serviceForms.githubRepoFormat')}
                </Form.Text>
            </Form.Group>

            {!useIntegration && (
                <Form.Group className="mb-3">
                    <Form.Label>
                        {t('globalIntegrations.accessToken')} <span className="text-danger">*</span>
                    </Form.Label>
                    <Form.Control
                        type="password"
                        name="github_token"
                        placeholder={t('serviceForms.githubTokenPlaceholder')}
                        value={formData.github_token}
                        onChange={handleChange}
                        className="rounded-3"
                        required={!useIntegration}
                    />
                    <Form.Text className="text-muted">
                        {t('serviceForms.githubTokenHelpBefore')}<code>repo</code>{t('serviceForms.tokenScopeAfter')}{" "}
                        <a
                            href="https://github.com/settings/tokens/new"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            {t('serviceForms.createOneHere')}
                        </a>
                    </Form.Text>
                </Form.Group>
            )}

            {/* Verification Section */}
            <div className="border rounded-3 p-3 mb-3 bg-light">
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{t('serviceForms.verifyConnection', { provider: 'GitHub' })}</strong>
                        <p className="text-muted small mb-0">
                            {t('serviceForms.verifyHint')}
                        </p>
                    </div>
                    <Button
                        variant={projectVerified ? "success" : "outline-primary"}
                        size="sm"
                        onClick={verifyGitHubProject}
                        disabled={verifying || !formData.github_repo || (!useIntegration && !formData.github_token)}
                    >
                        {verifying ? (
                            <>
                                <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                                {t('serviceForms.verifying')}
                            </>
                        ) : projectVerified ? (
                            <>✓ {t('serviceForms.verifiedLabel')}</>
                        ) : (
                            t('serviceForms.verify')
                        )}
                    </Button>
                </div>
                {verificationMessage && (
                    <Alert
                        variant={projectVerified ? "success" : "warning"}
                        className="mt-2 mb-0 py-2"
                    >
                        {verificationMessage}
                    </Alert>
                )}
            </div>
        </div>
    );
};

/**
 * BitbucketForm - Form for Bitbucket integration with OAuth2 verification
 */
export const BitbucketForm = ({
    formData,
    handleChange,
    verifyBitbucketProject,
    verifying,
    projectVerified,
    verificationMessage,
    integrations = []
}) => {
    const { t } = useTranslation();
    const { hasIntegrations, useIntegration, handleModeSwitch } = useIntegrationMode(
        integrations, formData, handleChange
    );

    return (
        <div className="bitbucket-service-form">
            {/* Integration Selector - shows prompt if no integrations */}
            {hasIntegrations ? (
                <div className="mb-3 p-3 bg-light rounded border">
                    <Form.Check
                        type="switch"
                        id="use-bb-int"
                        label={t('serviceForms.useGlobalIntegration', { provider: 'Bitbucket' })}
                        checked={useIntegration}
                        onChange={(e) => handleModeSwitch(e.target.checked)}
                        className="mb-2 fw-bold"
                    />
                    {useIntegration && (
                        <Form.Select
                            name="integration_id"
                            value={formData.integration_id}
                            onChange={handleChange}
                        >
                            {integrations.map(int => (
                                <option key={int.id} value={int.id}>{int.name}</option>
                            ))}
                        </Form.Select>
                    )}
                </div>
            ) : (
                <IntegrationPrompt providerType="bitbucket" />
            )}

            {useIntegration && (
                <RepoSelector
                    integrationId={formData.integration_id}
                    value={formData.bitbucket_repo}
                    onChange={(repo) => {
                        handleChange({ target: { name: 'bitbucket_repo', value: repo.full_name } });
                        if (!formData.name) handleChange({ target: { name: 'name', value: repo.name } });
                    }}
                    placeholder={t('serviceForms.selectRepoPlaceholder', { provider: 'Bitbucket' })}
                />
            )}

            <Form.Group className="mb-3">
                <Form.Label>{t('serviceForms.repository')} <span className="text-danger">*</span></Form.Label>
                <Form.Control type="text" name="bitbucket_repo" placeholder="workspace/repository-name" value={formData.bitbucket_repo} onChange={handleChange} className="rounded-3" required />
                <Form.Text className="text-muted">{t('serviceForms.bitbucketRepoFormat')}</Form.Text>
            </Form.Group>

            {!useIntegration && (
                <Form.Group className="mb-3">
                    <Form.Label>{t('serviceForms.oauth2AccessToken')} <span className="text-danger">*</span></Form.Label>
                    <Form.Control type="password" name="bitbucket_token" placeholder={t('serviceForms.bitbucketTokenPlaceholder')} value={formData.bitbucket_token} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                    <Form.Text className="text-muted">{t('serviceForms.bitbucketTokenHelpBefore')}<code>repository:read</code>{t('serviceForms.tokenScopeAfter')}</Form.Text>
                </Form.Group>
            )}

            {/* Verification Section */}
            <div className="border rounded-3 p-3 mb-3 bg-light">
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{t('serviceForms.verifyConnection', { provider: 'Bitbucket' })}</strong>
                        <p className="text-muted small mb-0">
                            {t('serviceForms.verifyHint')}
                        </p>
                    </div>
                    <Button
                        variant={projectVerified ? "success" : "outline-primary"}
                        size="sm"
                        onClick={verifyBitbucketProject}
                        disabled={verifying || !formData.bitbucket_repo || (!useIntegration && !formData.bitbucket_token)}
                    >
                        {verifying ? (
                            <>
                                <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                                {t('serviceForms.verifying')}
                            </>
                        ) : projectVerified ? (
                            <>✓ {t('serviceForms.verifiedLabel')}</>
                        ) : (
                            t('serviceForms.verify')
                        )}
                    </Button>
                </div>
                {verificationMessage && (
                    <Alert
                        variant={projectVerified ? "success" : "warning"}
                        className="mt-2 mb-0 py-2"
                    >
                        {verificationMessage}
                    </Alert>
                )}
            </div>
        </div>
    );
};

/**
 * AzureDevOpsForm - Form for Azure DevOps CI/CD integration
 */
export const AzureDevOpsForm = ({
    formData,
    handleChange,
    verifyAzureDevOpsProject,
    verifying,
    projectVerified,
    verificationMessage,
    integrations = []
}) => {
    const { t } = useTranslation();
    const { hasIntegrations, useIntegration, handleModeSwitch } = useIntegrationMode(
        integrations, formData, handleChange
    );

    return (
        <div className="azure-devops-service-form">
            {/* Integration Selector - shows prompt if no integrations */}
            {hasIntegrations ? (
                <div className="mb-3 p-3 bg-light rounded border">
                    <Form.Check
                        type="switch"
                        id="use-azure-int"
                        label={t('serviceForms.useGlobalIntegration', { provider: 'Azure DevOps' })}
                        checked={useIntegration}
                        onChange={(e) => handleModeSwitch(e.target.checked)}
                        className="mb-2 fw-bold"
                    />
                    {useIntegration && (
                        <Form.Select
                            name="integration_id"
                            value={formData.integration_id}
                            onChange={handleChange}
                        >
                            {integrations.map(int => (
                                <option key={int.id} value={int.id}>{int.name}</option>
                            ))}
                        </Form.Select>
                    )}
                </div>
            ) : (
                <IntegrationPrompt providerType="azure_devops" />
            )}

            {/* Hide Org/Project/PAT if using integration, assuming integration defines the Project level access context. 
            OR if Integration is Org level, we still need Project name. 
            Assuming Integration = Credentials + Org/Project Context. */
            }
            {!useIntegration && (
                <>
                    <Form.Group className="mb-3">
                        <Form.Label>{t('globalIntegrations.organization')} <span className="text-danger">*</span></Form.Label>
                        <Form.Control type="text" name="azure_organization" placeholder="your-organization" value={formData.azure_organization} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                    </Form.Group>

                    <Form.Group className="mb-3">
                        <Form.Label>{t('globalIntegrations.project')} <span className="text-danger">*</span></Form.Label>
                        <Form.Control type="text" name="azure_project" placeholder="your-project" value={formData.azure_project} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                    </Form.Group>

                    <Form.Group className="mb-3">
                        <Form.Label>{t('globalIntegrations.personalAccessToken')} <span className="text-danger">*</span></Form.Label>
                        <Form.Control type="password" name="azure_pat" placeholder={t('serviceForms.azurePatPlaceholder')} value={formData.azure_pat} onChange={handleChange} className="rounded-3" required={!useIntegration} />
                    </Form.Group>
                </>
            )}

            {/* Verification Section */}
            <div className="border rounded-3 p-3 mb-3 bg-light">
                <div className="d-flex justify-content-between align-items-center">
                    <div>
                        <strong>{t('serviceForms.verifyConnection', { provider: 'Azure DevOps' })}</strong>
                        <p className="text-muted small mb-0">
                            {t('serviceForms.verifyHint')}
                        </p>
                    </div>
                    <Button
                        variant={projectVerified ? "success" : "outline-primary"}
                        size="sm"
                        onClick={verifyAzureDevOpsProject}
                        disabled={verifying || (!useIntegration && (!formData.azure_organization || !formData.azure_project || !formData.azure_pat))}
                    >
                        {verifying ? (
                            <>
                                <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                                {t('serviceForms.verifying')}
                            </>
                        ) : projectVerified ? (
                            <>✓ {t('serviceForms.verifiedLabel')}</>
                        ) : (
                            t('serviceForms.verify')
                        )}
                    </Button>
                </div>
                {verificationMessage && (
                    <Alert
                        variant={projectVerified ? "success" : "warning"}
                        className="mt-2 mb-0 py-2"
                    >
                        {verificationMessage}
                    </Alert>
                )}
            </div>
        </div>
    );
};

/**
 * JenkinsForm - Form for Jenkins CI/CD integration
 */
export const JenkinsForm = ({ formData, handleChange, integrations = [] }) => {
    const { t } = useTranslation();
    const { hasIntegrations, useIntegration, handleModeSwitch } = useIntegrationMode(
        integrations, formData, handleChange
    );

    return (
        <div className="jenkins-service-form">
            {/* Integration Selector - shows prompt if no integrations */}
            {hasIntegrations ? (
                <div className="mb-3 p-3 bg-light rounded border">
                    <Form.Check
                        type="switch"
                        id="use-jenkins-int"
                        label={t('serviceForms.useGlobalIntegration', { provider: 'Jenkins' })}
                        checked={useIntegration}
                        onChange={(e) => handleModeSwitch(e.target.checked)}
                        className="mb-2 fw-bold"
                    />
                    {useIntegration && (
                        <Form.Select
                            name="integration_id"
                            value={formData.integration_id}
                            onChange={handleChange}
                        >
                            {integrations.map(int => (
                                <option key={int.id} value={int.id}>{int.name}</option>
                            ))}
                        </Form.Select>
                    )}
                </div>
            ) : (
                <IntegrationPrompt providerType="jenkins" />
            )}

            <Form.Group className="mb-3">
                <Form.Label>
                    {t('addService.serviceName')} <span className="text-danger">*</span>
                </Form.Label>
                <Form.Control
                    type="text"
                    name="name"
                    placeholder={t('serviceForms.namePlaceholderPipeline')}
                    value={formData.name}
                    onChange={handleChange}
                    className="rounded-3"
                    required
                />
            </Form.Group>

            {!useIntegration && (
                <>
                    <Form.Group className="mb-3">
                        <Form.Label>
                            {t('serviceForms.jenkinsUrl')} <span className="text-danger">*</span>
                        </Form.Label>
                        <Form.Control
                            type="url"
                            name="jenkins_url"
                            placeholder="https://jenkins.example.com"
                            value={formData.jenkins_url}
                            onChange={handleChange}
                            className="rounded-3"
                            required={!useIntegration}
                        />
                        <Form.Text className="text-muted">
                            {t('serviceForms.jenkinsUrlHelp')}
                        </Form.Text>
                    </Form.Group>

                    <Form.Group className="mb-3">
                        <Form.Label>
                            {t('globalIntegrations.apiToken')} <span className="text-danger">*</span>
                        </Form.Label>
                        <Form.Control
                            type="password"
                            name="jenkins_token"
                            placeholder={t('serviceForms.jenkinsTokenPlaceholder')}
                            value={formData.jenkins_token}
                            onChange={handleChange}
                            className="rounded-3"
                            required={!useIntegration}
                        />
                        <Form.Text className="text-muted">
                            {t('serviceForms.jenkinsTokenHelp')}
                        </Form.Text>
                    </Form.Group>

                    <Form.Group className="mb-3">
                        <Form.Label>{t('services.username')}</Form.Label>
                        <Form.Control
                            type="text"
                            name="jenkins_username"
                            placeholder={t('serviceForms.jenkinsUsernamePlaceholder')}
                            value={formData.jenkins_username}
                            onChange={handleChange}
                            className="rounded-3"
                        />
                    </Form.Group>
                </>
            )}

            <Form.Group className="mb-3">
                <Form.Label>{t('serviceForms.jobPipelineName')}</Form.Label>
                <Form.Control
                    type="text"
                    name="jenkins_job"
                    placeholder={t('serviceForms.jenkinsJobPlaceholder')}
                    value={formData.jenkins_job}
                    onChange={handleChange}
                    className="rounded-3"
                />
                <Form.Text className="text-muted">
                    {t('serviceForms.jenkinsJobHelp')}
                </Form.Text>
            </Form.Group>
        </div>
    );
};

// CICDBindingForm - Inline form for adding CI/CD binding during service creation
// Works with the unified binding model (uses global integrations)
export const CICDBindingForm = ({
    formData,
    handleChange,
    integrations = [],
    cicdProvider = "gitlab"
}) => {
    const { t } = useTranslation();
    const [fetchingPipelines, setFetchingPipelines] = React.useState(false);
    const [pipelines, setPipelines] = React.useState([]);

    // Get CI/CD provider display name
    const providerNames = {
        gitlab: "GitLab CI",
        github: "GitHub Actions",
        jenkins: "Jenkins",
        azure_devops: "Azure DevOps",
    };

    // Filter integrations for the selected CI/CD provider
    const cicdIntegrations = integrations.filter(i =>
        i.provider_type === cicdProvider && i.is_active
    );

    // Fetch pipelines when integration is selected
    React.useEffect(() => {
        if (formData.cicd_integration_id && cicdProvider) {
            fetchPipelines(formData.cicd_integration_id);
        }
    }, [formData.cicd_integration_id, cicdProvider]);

    const fetchPipelines = async (integrationId) => {
        if (!integrationId) return;

        setFetchingPipelines(true);
        try {
            // For GitLab/GitHub, pipelines are auto-detected from repo
            // For Jenkins/Azure, we might need to fetch job list
            if (cicdProvider === "jenkins") {
                const response = await IntegrationService.getJobs(integrationId);
                setPipelines(response.jobs || []);
            } else {
                // For GitLab/GitHub, pipeline is usually the repo itself
                setPipelines([]);
            }
        } catch (error) {
            console.error("Failed to fetch pipelines:", error);
            setPipelines([]);
        } finally {
            setFetchingPipelines(false);
        }
    };

    // No integrations configured for this provider
    if (cicdIntegrations.length === 0) {
        return (
            <IntegrationPrompt providerType={cicdProvider} />
        );
    }

    return (
        <div className="cicd-binding-form mt-3 p-3 border rounded-3 bg-light">
            <h6 className="mb-3 d-flex align-items-center">
                <FaCogs className="me-2 text-primary" />
                {t('serviceForms.providerPipeline', { provider: providerNames[cicdProvider] || "CI/CD" })}
            </h6>

            {/* Integration Selection */}
            <Form.Group className="mb-3">
                <Form.Label className="small fw-medium">
                    {t('serviceForms.providerIntegration', { provider: providerNames[cicdProvider] ?? "" })}
                </Form.Label>
                <Form.Select
                    name="cicd_integration_id"
                    value={formData.cicd_integration_id || ""}
                    onChange={handleChange}
                    className="rounded-3"
                >
                    <option value="">{t('serviceForms.selectIntegration')}</option>
                    {cicdIntegrations.map(integration => (
                        <option key={integration.id} value={integration.id}>
                            {integration.name}
                        </option>
                    ))}
                </Form.Select>
            </Form.Group>

            {/* Pipeline Type */}
            <Form.Group className="mb-3">
                <Form.Label className="small fw-medium">{t('serviceForms.pipelineType')}</Form.Label>
                <Form.Select
                    name="cicd_type"
                    value={formData.cicd_type || "build"}
                    onChange={handleChange}
                    className="rounded-3"
                >
                    <option value="build">{t('serviceForms.buildPipeline')}</option>
                    <option value="deploy">{t('serviceForms.deploymentPipeline')}</option>
                    <option value="test">{t('serviceForms.testPipeline')}</option>
                    <option value="release">{t('serviceForms.releasePipeline')}</option>
                </Form.Select>
            </Form.Group>

            {/* Pipeline ID/Name - depends on provider */}
            {cicdProvider === "jenkins" && pipelines.length > 0 ? (
                <Form.Group className="mb-3">
                    <Form.Label className="small fw-medium">{t('serviceForms.jobPipeline')}</Form.Label>
                    <Form.Select
                        name="cicd_pipeline_id"
                        value={formData.cicd_pipeline_id || ""}
                        onChange={handleChange}
                        className="rounded-3"
                        disabled={fetchingPipelines}
                    >
                        <option value="">{t('serviceForms.selectJob')}</option>
                        {pipelines.map(job => (
                            <option key={job.name} value={job.name}>
                                {job.name}
                            </option>
                        ))}
                    </Form.Select>
                </Form.Group>
            ) : cicdProvider === "azure_devops" ? (
                <Form.Group className="mb-3">
                    <Form.Label className="small fw-medium">{t('serviceForms.pipelineName')}</Form.Label>
                    <Form.Control
                        type="text"
                        name="cicd_pipeline_name"
                        placeholder={t('serviceForms.pipelineNamePlaceholder')}
                        value={formData.cicd_pipeline_name || ""}
                        onChange={handleChange}
                        className="rounded-3"
                    />
                </Form.Group>
            ) : (
                // GitLab/GitHub - Pipeline auto-detected from repo
                <Form.Text className="text-muted d-block mb-3">
                    <FaInfoCircle className="me-1" />
                    {t('serviceForms.pipelineAutoDetected')}
                </Form.Text>
            )}

            {/* Auto-trigger toggle */}
            <Form.Check
                type="switch"
                id="cicd-auto-trigger"
                label={t('serviceForms.autoTrigger')}
                checked={formData.cicd_auto_trigger !== false}
                onChange={(e) => handleChange({
                    target: { name: "cicd_auto_trigger", value: e.target.checked }
                })}
                className="small"
            />
        </div>
    );
};
