/**
 * DeploymentsPanel — Project detail "Deployments" tab (Batch 52).
 *
 * Renders the list of ProjectDeployment rows for a project + Add / Edit
 * / Delete controls. Only mounted when the parent decides to show the
 * tab (which auto-hides for projects with ≤1 deployment — SMB users
 * never see the concept).
 *
 * Each row displays the four scope dimensions as pills (env, cluster,
 * region, namespace) so the user can scan-down and see where each
 * copy of the project runs. Editing a deployment opens an inline
 * modal; delete has a confirmation step.
 *
 * "Namespace requires cluster" invariant enforced at both the model
 * layer (DB CheckConstraint) and the serializer — this component
 * surfaces the same rule with a disabled namespace input when no
 * cluster is chosen, so the user gets immediate feedback rather
 * than a 400 after Save.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Table, Button, Modal, Form, Badge, Spinner, Alert } from 'react-bootstrap';
import { FaPlus, FaTrash, FaEdit, FaServer, FaTag, FaGlobe, FaCube } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import DeploymentService from '../../services/deployment.service';
import ClusterService from '../../services/cluster.service';

// Environment options shipped as choices on AIAnalyzedBatch — kept in
// sync with backend ENVIRONMENT_CHOICES. Users create ProjectEnvironment
// rows separately (Environments tab), but for the Deployments UI we
// need the env dropdown to reflect what's actually available for this
// project. Loaded via the project detail props.
const EMPTY_FORM = {
    environment: '',
    cluster: '',
    region: '',
    namespace: '',
    name: '',
    is_active: true,
};

const DeploymentsPanel = ({ projectId, environments = [] }) => {
    const { t } = useTranslation();
    const [deployments, setDeployments] = useState([]);
    const [clusters, setClusters] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // Modal state — create + edit share the same form component.
    const [showModal, setShowModal] = useState(false);
    const [editing, setEditing] = useState(null); // deployment row or null (create)
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [formError, setFormError] = useState(null);

    // Delete confirmation state.
    const [deletingRow, setDeletingRow] = useState(null);

    const load = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            const [deps, clusterList] = await Promise.all([
                DeploymentService.list(projectId),
                ClusterService.list().catch(() => []),
            ]);
            setDeployments(deps);
            setClusters(Array.isArray(clusterList) ? clusterList.filter((c) => c.is_active) : []);
        } catch {
            setError(t('deployments.loadFailed', 'Failed to load deployments.'));
        } finally {
            setLoading(false);
        }
    }, [projectId, t]);

    useEffect(() => {
        load();
    }, [load]);

    // Modal helpers
    const openCreate = () => {
        setEditing(null);
        setForm({ ...EMPTY_FORM });
        setFormError(null);
        setShowModal(true);
    };

    const openEdit = (row) => {
        setEditing(row);
        setForm({
            environment: row.environment ?? '',
            cluster: row.cluster ?? '',
            region: row.region || '',
            namespace: row.namespace || '',
            name: row.name || '',
            is_active: row.is_active,
        });
        setFormError(null);
        setShowModal(true);
    };

    const closeModal = () => {
        setShowModal(false);
        setEditing(null);
    };

    const setField = (name, value) => {
        setForm((prev) => {
            const next = { ...prev, [name]: value };
            // Namespace-requires-cluster invariant: clearing cluster
            // clears any typed namespace so the user doesn't submit
            // a shape the DB will refuse.
            if (name === 'cluster' && !value) {
                next.namespace = '';
            }
            return next;
        });
    };

    const handleSave = async () => {
        setSaving(true);
        setFormError(null);
        try {
            const payload = {
                project: projectId,
                environment: form.environment || null,
                cluster: form.cluster || null,
                region: form.region || '',
                namespace: form.namespace || '',
                name: form.name || '',
                is_active: !!form.is_active,
            };
            if (editing) {
                await DeploymentService.update(editing.id, payload);
                toast.success(t('deployments.updated', 'Deployment updated.'));
            } else {
                await DeploymentService.create(payload);
                toast.success(t('deployments.created', 'Deployment created.'));
            }
            closeModal();
            await load();
        } catch (err) {
            // Try to surface the specific field error from the DRF
            // response so the user knows what to fix. Fall back to a
            // generic message.
            const data = err.response?.data;
            const msg =
                data?.non_field_errors?.[0]
                || data?.name?.[0]
                || data?.namespace?.[0]
                || data?.project?.[0]
                || data?.detail
                || t('deployments.saveFailed', 'Failed to save deployment.');
            setFormError(msg);
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!deletingRow) return;
        try {
            await DeploymentService.delete(deletingRow.id);
            toast.success(t('deployments.deleted', 'Deployment deleted.'));
            setDeletingRow(null);
            await load();
        } catch {
            toast.error(t('deployments.deleteFailed', 'Failed to delete deployment.'));
        }
    };

    if (loading) {
        return (
            <div className="text-center py-4">
                <Spinner animation="border" size="sm" />
            </div>
        );
    }

    return (
        <>
            <div className="d-flex justify-content-between align-items-center mb-3">
                <div>
                    <h5 className="mb-0">
                        {t('deployments.title', 'Deployments')}
                        <Badge bg="secondary" className="ms-2">{deployments.length}</Badge>
                    </h5>
                    <small className="text-muted">
                        {t('deployments.subtitle',
                            'One row per (env × cluster × region × namespace). Each deployment is analysed independently.')}
                    </small>
                </div>
                <Button
                    variant="primary"
                    size="sm"
                    className="rounded-pill px-3 d-flex align-items-center gap-2"
                    onClick={openCreate}
                >
                    <FaPlus size={12} /> {t('deployments.new', 'New deployment')}
                </Button>
            </div>

            {error && <Alert variant="danger">{error}</Alert>}

            {deployments.length === 0 ? (
                <div className="text-center py-4 text-muted border rounded bg-light">
                    <FaServer size={28} className="opacity-25 mb-2" />
                    <p className="mb-0">{t('deployments.empty', 'No deployments yet.')}</p>
                    <small>
                        {t('deployments.emptyHint',
                            'A default one gets auto-created per active environment. Add more here to model multi-cluster or multi-region deployments.')}
                    </small>
                </div>
            ) : (
                <div className="table-responsive">
                    <Table hover className="align-middle mb-0 table-stack">
                        <thead className="bg-light">
                            <tr>
                                <th className="ps-3 py-2 border-bottom">{t('deployments.name', 'Name')}</th>
                                <th className="py-2 border-bottom">{t('deployments.scope', 'Scope')}</th>
                                <th className="py-2 border-bottom">{t('deployments.status', 'Status')}</th>
                                <th className="pe-3 py-2 border-bottom text-end">{t('common.actions', 'Actions')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {deployments.map((d) => (
                                <tr key={d.id}>
                                    <td className="ps-3 fw-medium">{d.name}</td>
                                    <td>
                                        <ScopePills row={d} />
                                    </td>
                                    <td>
                                        <span className={`badge ${d.is_active ? 'bg-success bg-opacity-25 text-success' : 'bg-secondary bg-opacity-25 text-secondary'} rounded-pill px-2`}>
                                            {d.is_active ? t('deployments.active', 'Active') : t('deployments.inactive', 'Inactive')}
                                        </span>
                                    </td>
                                    <td className="text-end pe-3">
                                        <Button
                                            variant="light"
                                            size="sm"
                                            className="me-2"
                                            onClick={() => openEdit(d)}
                                            title={t('common.edit', 'Edit')}
                                        >
                                            <FaEdit size={12} />
                                        </Button>
                                        <Button
                                            variant="outline-danger"
                                            size="sm"
                                            onClick={() => setDeletingRow(d)}
                                            title={t('common.delete', 'Delete')}
                                        >
                                            <FaTrash size={12} />
                                        </Button>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </Table>
                </div>
            )}

            {/* Create / Edit modal */}
            <Modal show={showModal} onHide={closeModal} centered>
                <Modal.Header closeButton>
                    <Modal.Title>
                        {editing
                            ? t('deployments.editTitle', 'Edit deployment')
                            : t('deployments.newTitle', 'New deployment')}
                    </Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    {formError && <Alert variant="danger">{formError}</Alert>}
                    <Form>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('deployments.envLabel', 'Environment')}</Form.Label>
                            <Form.Select
                                value={form.environment}
                                onChange={(e) => setField('environment', e.target.value)}
                            >
                                <option value="">
                                    {t('deployments.envUnbound', '— none (legacy 0-env)')}
                                </option>
                                {environments.map((env) => (
                                    <option key={env.id} value={env.id}>
                                        {env.display_name || env.name}
                                    </option>
                                ))}
                            </Form.Select>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('deployments.clusterLabel', 'Cluster')}</Form.Label>
                            <Form.Select
                                value={form.cluster}
                                onChange={(e) => setField('cluster', e.target.value)}
                            >
                                <option value="">
                                    {t('deployments.clusterUnbound', '— none (VM / bare-metal)')}
                                </option>
                                {clusters.map((c) => (
                                    <option key={c.id} value={c.id}>
                                        {c.name} — {c.provider_display}
                                        {c.region ? ` (${c.region})` : ''}
                                    </option>
                                ))}
                            </Form.Select>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('deployments.regionLabel', 'Region')}</Form.Label>
                            <Form.Control
                                type="text"
                                placeholder={t('deployments.regionPlaceholder', 'us-east-1, eu-west-1, dc1…')}
                                value={form.region}
                                onChange={(e) => setField('region', e.target.value)}
                            />
                            <Form.Text className="text-muted">
                                {t('deployments.regionHelp',
                                    'Free-text. Used to distinguish multi-region deployments of the same project.')}
                            </Form.Text>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>
                                {t('deployments.namespaceLabel', 'Namespace')}
                                {!form.cluster && (
                                    <Badge bg="light" text="dark" className="ms-2">
                                        {t('deployments.nsDisabled', 'requires cluster')}
                                    </Badge>
                                )}
                            </Form.Label>
                            <Form.Control
                                type="text"
                                placeholder="payments, checkout, team-a…"
                                value={form.namespace}
                                onChange={(e) => setField('namespace', e.target.value)}
                                disabled={!form.cluster}
                            />
                            <Form.Text className="text-muted">
                                {t('deployments.nsHelp',
                                    'K8s namespace. Only available when a cluster is selected.')}
                            </Form.Text>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>
                                {t('deployments.nameLabel', 'Display name')}
                                <span className="text-muted small ms-2">{t('common.optional', '(optional)')}</span>
                            </Form.Label>
                            <Form.Control
                                type="text"
                                placeholder={t('deployments.nameAutoHint',
                                    'Auto-suggested from cluster / env / region on save')}
                                value={form.name}
                                onChange={(e) => setField('name', e.target.value)}
                            />
                        </Form.Group>

                        <Form.Check
                            type="switch"
                            id="deployment-active-switch"
                            label={t('deployments.activeLabel', 'Active — batch pipeline runs for this deployment')}
                            checked={!!form.is_active}
                            onChange={(e) => setField('is_active', e.target.checked)}
                        />
                    </Form>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={closeModal}>{t('common.cancel', 'Cancel')}</Button>
                    <Button variant="primary" onClick={handleSave} disabled={saving}>
                        {saving
                            ? <><Spinner size="sm" className="me-2" />{t('common.saving', 'Saving…')}</>
                            : t('common.save', 'Save')}
                    </Button>
                </Modal.Footer>
            </Modal>

            {/* Delete confirmation modal */}
            <Modal show={!!deletingRow} onHide={() => setDeletingRow(null)} centered size="sm">
                <Modal.Header closeButton>
                    <Modal.Title>{t('deployments.deleteConfirm', 'Delete deployment?')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>
                        {t('deployments.deleteBody',
                            'This stops the batch pipeline for this deployment. Existing batches keep their history but no new ones will be created.')}
                    </p>
                    {deletingRow && <p className="fw-semibold mb-0">{deletingRow.name}</p>}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setDeletingRow(null)}>
                        {t('common.cancel', 'Cancel')}
                    </Button>
                    <Button variant="danger" onClick={handleDelete}>
                        {t('common.delete', 'Delete')}
                    </Button>
                </Modal.Footer>
            </Modal>
        </>
    );
};

const ScopePills = ({ row }) => (
    <div className="d-flex flex-wrap gap-1">
        {row.environment_name && (
            <Badge bg="primary" className="d-inline-flex align-items-center gap-1 rounded-pill">
                <FaTag size={9} /> env={row.environment_name}
            </Badge>
        )}
        {row.cluster_name && (
            <Badge bg="info" className="d-inline-flex align-items-center gap-1 rounded-pill">
                <FaServer size={9} /> cluster={row.cluster_name}
            </Badge>
        )}
        {row.region && (
            <Badge bg="dark" className="d-inline-flex align-items-center gap-1 rounded-pill">
                <FaGlobe size={9} /> region={row.region}
            </Badge>
        )}
        {row.namespace && (
            <Badge bg="warning" text="dark" className="d-inline-flex align-items-center gap-1 rounded-pill">
                <FaCube size={9} /> ns={row.namespace}
            </Badge>
        )}
        {!row.environment_name && !row.cluster_name && !row.region && !row.namespace && (
            <span className="text-muted small">unscoped</span>
        )}
    </div>
);

export default DeploymentsPanel;
