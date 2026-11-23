/**
 * ServiceDetailsModal - Modal component for displaying service details
 * Supports unified service model with SCM and CI/CD bindings
 */

import React, { useState, useEffect } from "react";
import { Modal, Button, Row, Col, Alert, Badge, Table, Spinner, Form, Card } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { ProjectService } from "../../services/project.service";
import { IntegrationService } from "../../services/integration.service";
import { FaSync, FaLink, FaGit, FaGithub, FaGitlab, FaBitbucket, FaCloud, FaPlus, FaTrash, FaCog } from "react-icons/fa";
import { formatAbsolute } from '../../utils/dates';

const GITOPS_PROVIDERS = ['argocd', 'flux'];

// Where each sender posts, and how it authenticates (docs/src/integrations/
// jenkins.md and gitops.md). Argo CD and Flux can report to any binding; an
// Argo CD or Flux integration's binding is only for them.
const webhookTargets = (id, provider, t) => {
    const origin = window.location.origin;
    const targets = [];
    const argocd = { label: 'Argo CD', url: `${origin}/api/providers/webhook/argocd/${id}/`, auth: 'Authorization: Bearer <secret>' };
    const flux = { label: 'Flux', url: `${origin}/api/providers/webhook/flux/${id}/`, auth: 'generic-hmac Provider, token = <secret>' };
    if (provider === 'argocd') return [argocd];
    if (provider === 'flux') return [flux];
    if (provider === 'jenkins') {
        targets.push({ label: 'Jenkins', url: `${origin}/api/webhooks/jenkins/${id}/`, auth: t('services.webhookAuthJenkins') });
    } else if (provider) {
        const slug = provider === 'azure_devops' ? 'azure-devops' : provider;
        targets.push({ label: t('services.pipelineWebhook'), url: `${origin}/api/webhooks/${slug}/${id}/`, auth: t('services.webhookAuthSecret') });
    }
    targets.push(argocd, flux);
    return targets;
};

const WebhookDetails = ({ webhook, onClose }) => {
    const { t } = useTranslation();
    return (
    <Alert variant="warning" dismissible onClose={onClose} aria-label={t('services.webhookDetails')}>
        <strong>{t('services.copySecretNow')}</strong>{t('services.copySecretAfter')}
        <Form.Group className="mt-2" controlId="cicd-webhook-secret">
            <Form.Label className="small mb-1">{t('services.webhookSecret')}</Form.Label>
            <Form.Control readOnly value={webhook.secret} onFocus={(e) => e.target.select()} />
        </Form.Group>
        <Table size="sm" className="mt-2 mb-0 small">
            <tbody>
                {webhookTargets(webhook.id, webhook.provider, t).map((target) => (
                    <tr key={target.label}>
                        <th scope="row">{target.label}</th>
                        <td><code>{target.url}</code><div className="text-muted">{target.auth}</div></td>
                    </tr>
                ))}
            </tbody>
        </Table>
    </Alert>
    );
};

const ServiceDetailsModal = ({
    show,
    onHide,
    service,
    loading,
    error,
    onRefresh,
}) => {
    const { t } = useTranslation();
    const [performAction, setPerformAction] = useState({ loading: false, type: null, id: null });
    const [actionResult, setActionResult] = useState(null);

    // State for adding CI/CD bindings
    const [showAddCICD, setShowAddCICD] = useState(false);
    const [integrations, setIntegrations] = useState([]);
    const [newBinding, setNewBinding] = useState({
        integration_id: '',
        binding_type: 'build',
        pipeline_id: '',
        pipeline_name: '',
        auto_trigger: true,
    });
    const [addingBinding, setAddingBinding] = useState(false);
    // Webhook details for the binding just created. The secret is returned
    // only by the create call, so it is shown here once: without it, Jenkins,
    // Argo CD and Flux could not be pointed at SerOps from the UI.
    const [newWebhook, setNewWebhook] = useState(null);

    // Connecting a repository to a service that has none.
    const [showConnectRepo, setShowConnectRepo] = useState(false);
    const [repoForm, setRepoForm] = useState({ integration: '', repository: '' });
    const [repos, setRepos] = useState([]);
    const [reposState, setReposState] = useState({ loading: false, error: null });
    const [connecting, setConnecting] = useState(false);
    const SCM_PROVIDERS = ['gitlab', 'github', 'bitbucket', 'azure_devops'];
    const scmIntegrations = integrations.filter(i => SCM_PROVIDERS.includes(i.provider_type) && i.is_active);

    useEffect(() => {
        if (!repoForm.integration) { setRepos([]); return; }
        setReposState({ loading: true, error: null });
        IntegrationService.getRepos(repoForm.integration)
            .then(data => {
                const list = Array.isArray(data) ? data : data.results || data.repositories || [];
                setRepos(list);
                setReposState({ loading: false, error: null });
            })
            .catch(() => setReposState({ loading: false, error: 'services.listReposFailed' }));
    }, [repoForm.integration]);

    const repoKey = (r) => String(r.id || r.full_name || r.path_with_namespace);
    const handleConnectRepo = async () => {
        const repo = repos.find(r => repoKey(r) === repoForm.repository);
        if (!repoForm.integration || !repo) return;
        setConnecting(true);
        try {
            await ProjectService.addSCMBinding(service.id, {
                integration: repoForm.integration,
                repository_id: repo.id || repo.full_name || repo.path_with_namespace,
                repository_name: repo.full_name || repo.name || repo.path_with_namespace,
                repository_url: repo.html_url || repo.web_url || repo.url || '',
                default_branch: repo.default_branch,
            });
            setActionResult({ type: 'success', message: t('services.repoConnected') });
            setShowConnectRepo(false);
            setRepoForm({ integration: '', repository: '' });
            if (onRefresh) onRefresh();
        } catch (err) {
            const detail = err?.response?.data;
            setActionResult({ type: 'danger', message: t('services.connectRepoFailed', { error: detail ? JSON.stringify(detail) : err.message }) });
        } finally {
            setConnecting(false);
        }
    };

    // Fetch integrations for the CI/CD binding and repository forms
    useEffect(() => {
        if ((showAddCICD || showConnectRepo) && integrations.length === 0) {
            IntegrationService.getAll()
                .then(data => setIntegrations(Array.isArray(data) ? data : data.results || []))
                .catch(err => console.error('Failed to load integrations:', err));
        }
    }, [showAddCICD, showConnectRepo]);

    // CI/CD provider types (must match SettingsIntegrations capability definitions)
    const CICD_PROVIDERS = ['gitlab', 'github', 'azure_devops', 'jenkins', 'bitbucket', ...GITOPS_PROVIDERS];
    const cicdIntegrations = integrations.filter(i => CICD_PROVIDERS.includes(i.provider_type) && i.is_active);
    const newBindingProvider = integrations.find((i) => String(i.id) === String(newBinding.integration_id))?.provider_type;
    const newBindingIsGitOps = GITOPS_PROVIDERS.includes(newBindingProvider);
    // GitHub Actions and GitLab CI pipelines are the repository / project,
    // not a job (phase 3 C1: a workflow file went there and every sync failed).
    const newBindingPlaceholder = newBindingIsGitOps ? t('services.appPlaceholder')
        : newBindingProvider === 'github' ? 'owner/repo'
        : newBindingProvider === 'gitlab' ? t('services.gitlabPipelinePlaceholder')
        : t('services.jobPlaceholder');

    const handleAddCICDBinding = async () => {
        if (!newBinding.integration_id || !newBinding.pipeline_id) return;

        setAddingBinding(true);
        try {
            const created = await ProjectService.addCICDBinding(service.id, newBinding);
            setActionResult({ type: 'success', message: t('services.bindingAdded') });
            if (created?.id && created?.webhook_secret) {
                const provider = integrations.find((i) => String(i.id) === String(newBinding.integration_id))?.provider_type;
                setNewWebhook({ id: created.id, secret: created.webhook_secret, provider });
            }
            setShowAddCICD(false);
            setNewBinding({ integration_id: '', binding_type: 'build', pipeline_id: '', pipeline_name: '', auto_trigger: true });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: t('services.addBindingFailed', { error: err.message || t('services.unknownError') }) });
        } finally {
            setAddingBinding(false);
        }
    };

    const handleDeleteBinding = async (bindingId) => {
        if (!window.confirm(t('services.removeBindingConfirm'))) return;
        try {
            await ProjectService.deleteCICDBinding(bindingId);
            setActionResult({ type: 'success', message: t('services.bindingRemoved') });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: t('services.removeBindingFailed') });
        }
    };

    const handleSync = async (bindingId) => {
        setPerformAction({ loading: true, type: 'sync', id: bindingId });
        setActionResult(null);
        try {
            await ProjectService.SyncSCMBinding(bindingId);
            setActionResult({ type: 'success', message: t('services.syncStarted') });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: t('services.syncFailed', { error: err.response?.data?.error || err.message }) });
        } finally {
            setPerformAction({ loading: false, type: null, id: null });
        }
    };

    const handleSetupWebhook = async (bindingId) => {
        setPerformAction({ loading: true, type: 'webhook', id: bindingId });
        setActionResult(null);
        try {
            await ProjectService.SetupSCMWebhook(bindingId);
            setActionResult({ type: 'success', message: t('services.webhookConfigured') });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: t('services.webhookSetupFailed', { error: err.response?.data?.error || err.message }) });
        } finally {
            setPerformAction({ loading: false, type: null, id: null });
        }
    };


    return (
        <Modal show={show} onHide={onHide} centered size="lg">
            <Modal.Body className="p-0">
                <div className="d-flex flex-column">
                    {/* Header section */}
                    <div className="bg-primary bg-opacity-10 p-4">
                        <div className="d-flex justify-content-between align-items-center">
                            <div>
                                <h4 className="mb-1">
                                    {service?.name || t('services.serviceNumber', { id: service?.id })}
                                </h4>
                                <span className="badge bg-primary bg-opacity-75 text-white rounded-pill px-3">
                                    {/* Its type, not whether it has a repository: an Application
                                        without an SCM binding read "Custom Service" (B23). */}
                                    {{
                                        application: t('services.typeApplication', 'Application'),
                                        infrastructure: t('services.typeInfrastructure', 'Infrastructure'),
                                    }[service?.service_type] || t('services.customService')}
                                </span>
                            </div>
                            <Button variant="close" onClick={onHide}></Button>
                        </div>
                    </div>

                    {/* Content section */}
                    <div className="p-4">
                        {loading ? (
                            <div className="text-center py-4">
                                <Spinner animation="border" role="status" />
                                <p className="mt-2">{t('services.loadingDetails')}</p>
                            </div>
                        ) : error ? (
                            <Alert variant="danger" className="d-flex align-items-center">
                                <i className="fas fa-exclamation-triangle me-2"></i>
                                {error}
                            </Alert>
                        ) : service ? (
                            <div className="d-flex flex-column gap-4">
                                {newWebhook && (
                                    <WebhookDetails webhook={newWebhook} onClose={() => setNewWebhook(null)} />
                                )}
                                {actionResult && (
                                    <Alert variant={actionResult.type} dismissible onClose={() => setActionResult(null)}>
                                        {actionResult.message}
                                    </Alert>
                                )}

                                {/* SCM Binding Section */}
                                {service.scm_binding && (
                                    <div className="card shadow-sm border-0">
                                        <div className="card-header bg-white border-bottom-0 pt-3">
                                            <div className="d-flex align-items-center">
                                                <FaGit className="text-secondary me-2" size={20} />
                                                <h5 className="mb-0 text-dark">{t('services.sourceControlIntegration')}</h5>
                                                {service.scm_binding.provider_type === 'gitlab' && <FaGitlab className="ms-auto text-warning" size={24} />}
                                                {service.scm_binding.provider_type === 'github' && <FaGithub className="ms-auto text-dark" size={24} />}
                                                {service.scm_binding.provider_type === 'bitbucket' && <FaBitbucket className="ms-auto text-primary" size={24} />}
                                                {service.scm_binding.provider_type === 'azure_devops' && <FaCloud className="ms-auto" size={24} style={{ color: '#0078D7' }} />}
                                            </div>
                                        </div>
                                        <div className="card-body">
                                            <Row className="g-3">
                                                <Col md={6}>
                                                    <label className="text-muted small">{t('serviceForms.repository')}</label>
                                                    <div className="fw-bold">{service.scm_binding.repository_name}</div>
                                                </Col>
                                                <Col md={6}>
                                                    <label className="text-muted small">{t('services.branch')}</label>
                                                    <div><Badge bg="light" text="dark" className="border">{service.scm_binding.default_branch || 'HEAD'}</Badge></div>
                                                </Col>
                                                <Col md={12}>
                                                    <label className="text-muted small">{t('services.cloneUrl')}</label>
                                                    <code className="d-block p-2 bg-light rounded text-break">{service.scm_binding.repository_url}</code>
                                                </Col>

                                                <Col md={12} className="border-top pt-3 mt-3">
                                                    <div className="d-flex justify-content-between align-items-center">
                                                        <div className="d-flex align-items-center gap-3">
                                                            <div className="d-flex align-items-center">
                                                                <div className={`rounded-circle me-2 ${service.scm_binding.webhook_configured ? 'bg-success' : 'bg-secondary'}`} style={{ width: 8, height: 8 }}></div>
                                                                <small>{service.scm_binding.webhook_configured ? t('services.webhookActiveShort') : t('services.webhookNotConfiguredShort')}</small>
                                                            </div>
                                                            {service.scm_binding.last_sync_at && (
                                                                <small className="text-muted">{t('services.lastSync', { date: formatAbsolute(service.scm_binding.last_sync_at, { seconds: false }) })}</small>
                                                            )}
                                                        </div>
                                                        <div className="d-flex gap-2">
                                                            {!service.scm_binding.webhook_configured && (
                                                                <Button
                                                                    variant="outline-primary"
                                                                    size="sm"
                                                                    onClick={() => handleSetupWebhook(service.scm_binding.id)}
                                                                    disabled={performAction.loading}
                                                                >
                                                                    {performAction.loading && performAction.type === 'webhook' && performAction.id === service.scm_binding.id ? <Spinner size="sm" animation="border" /> : t('services.setupWebhook')}
                                                                </Button>
                                                            )}
                                                            <Button
                                                                variant="light"
                                                                size="sm"
                                                                onClick={() => handleSync(service.scm_binding.id)}
                                                                disabled={performAction.loading}
                                                                title={t('services.syncCommits')}
                                                            >
                                                                <FaSync className={performAction.loading && performAction.type === 'sync' && performAction.id === service.scm_binding.id ? "fa-spin" : ""} />
                                                            </Button>
                                                        </div>
                                                    </div>
                                                    {service.scm_binding.sync_error && (
                                                        <div className="text-danger small mt-2">{t('services.syncError', { error: service.scm_binding.sync_error })}</div>
                                                    )}
                                                </Col>
                                            </Row>
                                        </div>
                                    </div>
                                )}

                                {!service.scm_binding && (
                                    <div className="card shadow-sm border-0">
                                        <div className="card-header bg-white border-bottom-0 pt-3 d-flex justify-content-between align-items-center">
                                            <div className="d-flex align-items-center">
                                                <FaGit className="text-secondary me-2" />
                                                <h5 className="mb-0 text-dark">{t('services.codeRepository')}</h5>
                                            </div>
                                            <Button variant="outline-primary" size="sm" onClick={() => setShowConnectRepo(!showConnectRepo)}>
                                                <FaLink className="me-1" /> {t('services.connectRepository')}
                                            </Button>
                                        </div>
                                        {showConnectRepo ? (
                                            <Card.Body className="border-bottom bg-light">
                                                <Row className="g-2 align-items-end">
                                                    <Col md={4}>
                                                        <Form.Label className="small mb-1" htmlFor="scm-binding-integration">{t('addService.integration')}</Form.Label>
                                                        <Form.Select id="scm-binding-integration" size="sm" value={repoForm.integration}
                                                            onChange={(e) => setRepoForm({ integration: e.target.value, repository: '' })}>
                                                            <option value="">{t('services.selectEllipsis')}</option>
                                                            {scmIntegrations.map(i => <option key={i.id} value={i.id}>{i.name} ({i.provider_type})</option>)}
                                                        </Form.Select>
                                                    </Col>
                                                    <Col md={5}>
                                                        <Form.Label className="small mb-1" htmlFor="scm-binding-repository">{t('serviceForms.repository')}</Form.Label>
                                                        <Form.Select id="scm-binding-repository" size="sm" value={repoForm.repository}
                                                            disabled={!repoForm.integration || reposState.loading}
                                                            onChange={(e) => setRepoForm({ ...repoForm, repository: e.target.value })}>
                                                            <option value="">{reposState.loading ? t('services.loadingEllipsis') : t('services.selectEllipsis')}</option>
                                                            {repos.map(r => <option key={repoKey(r)} value={repoKey(r)}>{r.full_name || r.name || r.path_with_namespace}</option>)}
                                                        </Form.Select>
                                                    </Col>
                                                    <Col md={3}>
                                                        <Button size="sm" className="w-100" onClick={handleConnectRepo}
                                                            disabled={connecting || !repoForm.repository}>
                                                            {connecting ? <Spinner size="sm" animation="border" /> : t('services.connect')}
                                                        </Button>
                                                    </Col>
                                                </Row>
                                                {reposState.error && <div className="text-danger small mt-2">{t(reposState.error)}</div>}
                                                {!scmIntegrations.length && integrations.length > 0 && (
                                                    <div className="small text-muted mt-2">{t('services.addScmFirst')}</div>
                                                )}
                                            </Card.Body>
                                        ) : (
                                            <Card.Body className="pt-0 small text-muted">
                                                {t('services.noRepoConnected')}
                                            </Card.Body>
                                        )}
                                    </div>
                                )}

                                {/* CI/CD Bindings Section */}
                                <div className="card shadow-sm border-0">
                                    <div className="card-header bg-white border-bottom-0 pt-3 d-flex justify-content-between align-items-center">
                                        <div className="d-flex align-items-center">
                                            <FaCog className="text-secondary me-2" />
                                            <h5 className="mb-0 text-dark">{t('services.cicdPipelines')}</h5>
                                            {service.cicd_bindings?.length > 0 && (
                                                <Badge bg="primary" className="ms-2">{service.cicd_bindings.length}</Badge>
                                            )}
                                        </div>
                                        <Button
                                            variant="outline-primary"
                                            size="sm"
                                            onClick={() => setShowAddCICD(!showAddCICD)}
                                        >
                                            <FaPlus className="me-1" /> {t('services.addPipeline')}
                                        </Button>
                                    </div>

                                    {/* Add CI/CD Binding Form */}
                                    {showAddCICD && (
                                        <Card.Body className="border-bottom bg-light">
                                            <Row className="g-2 align-items-end">
                                                <Col md={3}>
                                                    <Form.Label className="small mb-1" htmlFor="cicd-binding-integration">{t('addService.integration')}</Form.Label>
                                                    <Form.Select
                                                        id="cicd-binding-integration"
                                                        size="sm"
                                                        value={newBinding.integration_id}
                                                        onChange={(e) => {
                                                            const picked = integrations.find((i) => String(i.id) === e.target.value);
                                                            // Argo CD and Flux only deploy.
                                                            const gitops = GITOPS_PROVIDERS.includes(picked?.provider_type);
                                                            setNewBinding({ ...newBinding, integration_id: e.target.value, ...(gitops ? { binding_type: 'deploy' } : {}) });
                                                        }}
                                                    >
                                                        <option value="">{t('services.selectDots')}</option>
                                                        {cicdIntegrations.map(int => (
                                                            <option key={int.id} value={int.id}>{int.name}</option>
                                                        ))}
                                                    </Form.Select>
                                                </Col>
                                                <Col md={2}>
                                                    <Form.Label className="small mb-1" htmlFor="cicd-binding-type">{t('services.type')}</Form.Label>
                                                    <Form.Select
                                                        id="cicd-binding-type"
                                                        size="sm"
                                                        value={newBinding.binding_type}
                                                        onChange={(e) => setNewBinding({ ...newBinding, binding_type: e.target.value })}
                                                    >
                                                        <option value="build">{t('services.bindingTypeBuild')}</option>
                                                        <option value="deploy">{t('services.bindingTypeDeploy')}</option>
                                                        <option value="test">{t('services.bindingTypeTest')}</option>
                                                        <option value="release">{t('services.bindingTypeRelease')}</option>
                                                    </Form.Select>
                                                </Col>
                                                <Col md={3}>
                                                    <Form.Label className="small mb-1" htmlFor="cicd-binding-pipeline">{newBindingIsGitOps ? t('services.gitopsApplication') : t('services.pipelineId')}</Form.Label>
                                                    <Form.Control
                                                        id="cicd-binding-pipeline"
                                                        size="sm"
                                                        type="text"
                                                        placeholder={newBindingPlaceholder}
                                                        value={newBinding.pipeline_id}
                                                        onChange={(e) => setNewBinding({ ...newBinding, pipeline_id: e.target.value })}
                                                    />
                                                </Col>
                                                <Col md={2}>
                                                    <Form.Label className="small mb-1" htmlFor="cicd-binding-name">{t('services.bindingName')}</Form.Label>
                                                    <Form.Control
                                                        id="cicd-binding-name"
                                                        size="sm"
                                                        type="text"
                                                        placeholder={t('services.optionalPlaceholder')}
                                                        value={newBinding.pipeline_name}
                                                        onChange={(e) => setNewBinding({ ...newBinding, pipeline_name: e.target.value })}
                                                    />
                                                </Col>
                                                <Col md={2}>
                                                    <Button
                                                        variant="primary"
                                                        size="sm"
                                                        onClick={handleAddCICDBinding}
                                                        disabled={addingBinding || !newBinding.integration_id || !newBinding.pipeline_id}
                                                        className="w-100"
                                                    >
                                                        {addingBinding ? <Spinner size="sm" animation="border" /> : t('common.add')}
                                                    </Button>
                                                </Col>
                                            </Row>
                                        </Card.Body>
                                    )}

                                    {service.cicd_bindings && service.cicd_bindings.length > 0 ? (
                                        <Table hover responsive className="mb-0">
                                            <thead className="bg-light">
                                                <tr>
                                                    <th className="border-0">{t('services.type')}</th>
                                                    <th className="border-0">{t('services.pipeline')}</th>
                                                    <th className="border-0">{t('services.status')}</th>
                                                    <th className="border-0">{t('services.autoTrigger')}</th>
                                                    <th className="border-0 text-end">{t('common.actions')}</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {service.cicd_bindings.map(binding => (
                                                    <tr key={binding.id}>
                                                        <td>{binding.binding_type_display}</td>
                                                        <td>
                                                            <a href={binding.pipeline_url} target="_blank" rel="noopener noreferrer" className="text-decoration-none">
                                                                {binding.pipeline_name || binding.pipeline_id} <FaLink size={10} />
                                                            </a>
                                                        </td>
                                                        <td>{binding.sync_error ? <Badge bg="danger">{t('common.error')}</Badge> : <Badge bg="success">{t('services.active')}</Badge>}</td>
                                                        <td>
                                                            {binding.auto_trigger ? <Badge bg="info">{t('services.on')}</Badge> : <Badge bg="secondary">{t('services.off')}</Badge>}
                                                        </td>
                                                        <td className="text-end">
                                                            <Button
                                                                variant="link"
                                                                size="sm"
                                                                className="text-danger p-0"
                                                                onClick={() => handleDeleteBinding(binding.id)}
                                                                title={t('services.removeBinding')}
                                                            >
                                                                <FaTrash size={12} />
                                                            </Button>
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </Table>
                                    ) : (
                                        !showAddCICD && (
                                            <Card.Body className="text-center text-muted py-4">
                                                <p className="mb-0">{t('services.noPipelines')}</p>
                                                <small>{t('services.noPipelinesHint')}</small>
                                            </Card.Body>
                                        )
                                    )}
                                </div>

                            </div>
                        ) : (
                            <Alert variant="warning">{t('services.noServiceSelected')}</Alert>
                        )}
                    </div>


                    {/* Footer section */}
                    <div className="border-top p-3 text-end">
                        <Button
                            variant="primary"
                            onClick={onHide}
                            className="rounded-pill px-4"
                        >
                            {t('common.close')}
                        </Button>
                    </div>
                </div>
            </Modal.Body>
        </Modal>
    );
};

export default ServiceDetailsModal;
