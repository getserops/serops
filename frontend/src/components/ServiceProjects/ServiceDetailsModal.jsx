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

    // Fetch integrations for CI/CD binding form
    useEffect(() => {
        if (showAddCICD && integrations.length === 0) {
            IntegrationService.getAll()
                .then(data => setIntegrations(Array.isArray(data) ? data : data.results || []))
                .catch(err => console.error('Failed to load integrations:', err));
        }
    }, [showAddCICD]);

    // CI/CD provider types (must match SettingsIntegrations capability definitions)
    const CICD_PROVIDERS = ['gitlab', 'github', 'azure_devops', 'jenkins', 'bitbucket'];
    const cicdIntegrations = integrations.filter(i => CICD_PROVIDERS.includes(i.provider_type) && i.is_active);

    const handleAddCICDBinding = async () => {
        if (!newBinding.integration_id || !newBinding.pipeline_id) return;

        setAddingBinding(true);
        try {
            await ProjectService.addCICDBinding(service.id, newBinding);
            setActionResult({ type: 'success', message: 'CI/CD binding added successfully!' });
            setShowAddCICD(false);
            setNewBinding({ integration_id: '', binding_type: 'build', pipeline_id: '', pipeline_name: '', auto_trigger: true });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: 'Failed to add binding: ' + (err.message || 'Unknown error') });
        } finally {
            setAddingBinding(false);
        }
    };

    const handleDeleteBinding = async (bindingId) => {
        if (!window.confirm('Remove this CI/CD binding?')) return;
        try {
            await ProjectService.deleteCICDBinding(bindingId);
            setActionResult({ type: 'success', message: 'Binding removed successfully!' });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: 'Failed to remove binding' });
        }
    };

    const handleSync = async (bindingId) => {
        setPerformAction({ loading: true, type: 'sync', id: bindingId });
        setActionResult(null);
        try {
            await ProjectService.SyncSCMBinding(bindingId);
            setActionResult({ type: 'success', message: 'Sync started successfully' });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: 'Sync failed: ' + (err.response?.data?.error || err.message) });
        } finally {
            setPerformAction({ loading: false, type: null, id: null });
        }
    };

    const handleSetupWebhook = async (bindingId) => {
        setPerformAction({ loading: true, type: 'webhook', id: bindingId });
        setActionResult(null);
        try {
            await ProjectService.SetupSCMWebhook(bindingId);
            setActionResult({ type: 'success', message: 'Webhook configured successfully' });
            if (onRefresh) onRefresh();
        } catch (err) {
            setActionResult({ type: 'danger', message: 'Webhook setup failed: ' + (err.response?.data?.error || err.message) });
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
                                    {service?.name || `Service #${service?.id}`}
                                </h4>
                                <span className="badge bg-primary bg-opacity-75 text-white rounded-pill px-3">
                                    {service?.scm_binding ? t('services.gitlabProject') : t('services.customService')}
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
                                                <h5 className="mb-0 text-dark">Source Control Integration</h5>
                                                {service.scm_binding.provider_type === 'gitlab' && <FaGitlab className="ms-auto text-warning" size={24} />}
                                                {service.scm_binding.provider_type === 'github' && <FaGithub className="ms-auto text-dark" size={24} />}
                                                {service.scm_binding.provider_type === 'bitbucket' && <FaBitbucket className="ms-auto text-primary" size={24} />}
                                                {service.scm_binding.provider_type === 'azure_devops' && <FaCloud className="ms-auto" size={24} style={{ color: '#0078D7' }} />}
                                            </div>
                                        </div>
                                        <div className="card-body">
                                            <Row className="g-3">
                                                <Col md={6}>
                                                    <label className="text-muted small">Repository</label>
                                                    <div className="fw-bold">{service.scm_binding.repository_name}</div>
                                                </Col>
                                                <Col md={6}>
                                                    <label className="text-muted small">Branch</label>
                                                    <div><Badge bg="light" text="dark" className="border">{service.scm_binding.default_branch || 'HEAD'}</Badge></div>
                                                </Col>
                                                <Col md={12}>
                                                    <label className="text-muted small">Clone URL</label>
                                                    <code className="d-block p-2 bg-light rounded text-break">{service.scm_binding.repository_url}</code>
                                                </Col>

                                                <Col md={12} className="border-top pt-3 mt-3">
                                                    <div className="d-flex justify-content-between align-items-center">
                                                        <div className="d-flex align-items-center gap-3">
                                                            <div className="d-flex align-items-center">
                                                                <div className={`rounded-circle me-2 ${service.scm_binding.webhook_configured ? 'bg-success' : 'bg-secondary'}`} style={{ width: 8, height: 8 }}></div>
                                                                <small>{service.scm_binding.webhook_configured ? 'Webhook Active' : 'Webhook Not Configured'}</small>
                                                            </div>
                                                            {service.scm_binding.last_sync_at && (
                                                                <small className="text-muted">Last sync: {new Date(service.scm_binding.last_sync_at).toLocaleString()}</small>
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
                                                                    {performAction.loading && performAction.type === 'webhook' && performAction.id === service.scm_binding.id ? <Spinner size="sm" animation="border" /> : 'Setup Webhook'}
                                                                </Button>
                                                            )}
                                                            <Button
                                                                variant="light"
                                                                size="sm"
                                                                onClick={() => handleSync(service.scm_binding.id)}
                                                                disabled={performAction.loading}
                                                                title="Sync Commits"
                                                            >
                                                                <FaSync className={performAction.loading && performAction.type === 'sync' && performAction.id === service.scm_binding.id ? "fa-spin" : ""} />
                                                            </Button>
                                                        </div>
                                                    </div>
                                                    {service.scm_binding.sync_error && (
                                                        <div className="text-danger small mt-2">Sync Error: {service.scm_binding.sync_error}</div>
                                                    )}
                                                </Col>
                                            </Row>
                                        </div>
                                    </div>
                                )}

                                {/* CI/CD Bindings Section */}
                                <div className="card shadow-sm border-0">
                                    <div className="card-header bg-white border-bottom-0 pt-3 d-flex justify-content-between align-items-center">
                                        <div className="d-flex align-items-center">
                                            <FaCog className="text-secondary me-2" />
                                            <h5 className="mb-0 text-dark">CI/CD Pipelines</h5>
                                            {service.cicd_bindings?.length > 0 && (
                                                <Badge bg="primary" className="ms-2">{service.cicd_bindings.length}</Badge>
                                            )}
                                        </div>
                                        <Button
                                            variant="outline-primary"
                                            size="sm"
                                            onClick={() => setShowAddCICD(!showAddCICD)}
                                        >
                                            <FaPlus className="me-1" /> Add Pipeline
                                        </Button>
                                    </div>

                                    {/* Add CI/CD Binding Form */}
                                    {showAddCICD && (
                                        <Card.Body className="border-bottom bg-light">
                                            <Row className="g-2 align-items-end">
                                                <Col md={3}>
                                                    <Form.Label className="small mb-1">Integration</Form.Label>
                                                    <Form.Select
                                                        size="sm"
                                                        value={newBinding.integration_id}
                                                        onChange={(e) => setNewBinding({ ...newBinding, integration_id: e.target.value })}
                                                    >
                                                        <option value="">Select...</option>
                                                        {cicdIntegrations.map(int => (
                                                            <option key={int.id} value={int.id}>{int.name}</option>
                                                        ))}
                                                    </Form.Select>
                                                </Col>
                                                <Col md={2}>
                                                    <Form.Label className="small mb-1">Type</Form.Label>
                                                    <Form.Select
                                                        size="sm"
                                                        value={newBinding.binding_type}
                                                        onChange={(e) => setNewBinding({ ...newBinding, binding_type: e.target.value })}
                                                    >
                                                        <option value="build">Build</option>
                                                        <option value="deploy">Deploy</option>
                                                        <option value="test">Test</option>
                                                        <option value="release">Release</option>
                                                    </Form.Select>
                                                </Col>
                                                <Col md={3}>
                                                    <Form.Label className="small mb-1">Pipeline ID</Form.Label>
                                                    <Form.Control
                                                        size="sm"
                                                        type="text"
                                                        placeholder="e.g., job/my-job"
                                                        value={newBinding.pipeline_id}
                                                        onChange={(e) => setNewBinding({ ...newBinding, pipeline_id: e.target.value })}
                                                    />
                                                </Col>
                                                <Col md={2}>
                                                    <Form.Label className="small mb-1">Name</Form.Label>
                                                    <Form.Control
                                                        size="sm"
                                                        type="text"
                                                        placeholder="Optional"
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
                                                        {addingBinding ? <Spinner size="sm" animation="border" /> : 'Add'}
                                                    </Button>
                                                </Col>
                                            </Row>
                                        </Card.Body>
                                    )}

                                    {service.cicd_bindings && service.cicd_bindings.length > 0 ? (
                                        <Table hover responsive className="mb-0">
                                            <thead className="bg-light">
                                                <tr>
                                                    <th className="border-0">Type</th>
                                                    <th className="border-0">Pipeline</th>
                                                    <th className="border-0">Status</th>
                                                    <th className="border-0">Auto-Trigger</th>
                                                    <th className="border-0 text-end">Actions</th>
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
                                                        <td>{binding.sync_error ? <Badge bg="danger">Error</Badge> : <Badge bg="success">Active</Badge>}</td>
                                                        <td>
                                                            {binding.auto_trigger ? <Badge bg="info">On</Badge> : <Badge bg="secondary">Off</Badge>}
                                                        </td>
                                                        <td className="text-end">
                                                            <Button
                                                                variant="link"
                                                                size="sm"
                                                                className="text-danger p-0"
                                                                onClick={() => handleDeleteBinding(binding.id)}
                                                                title="Remove binding"
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
                                                <p className="mb-0">No CI/CD pipelines configured</p>
                                                <small>Click "Add Pipeline" to connect a CI/CD integration</small>
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
