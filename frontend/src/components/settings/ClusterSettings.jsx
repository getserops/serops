/**
 * Cluster Settings — manage K8s / VM clusters for the org (Item #17).
 *
 * A logs-only or single-cluster user won't hit this page — it's only
 * useful when you have multiple K8s clusters and want to scope
 * Prometheus / Loki / etc. per cluster. Discoverable under
 * Settings → Clusters.
 *
 * Admin-only (backend enforces IsAdminRole on write endpoints; read
 * endpoint is authenticated so we can display a read-only view for
 * non-admins if we ever want that — for now the sidebar link is
 * shown to admins).
 */

import React, { useState, useEffect, useCallback } from 'react';
import PageHeader from '../PageHeader';
import { Button, Modal, Form, Spinner, Table, Alert, Badge } from 'react-bootstrap';
import {
    FaServer, FaPlus, FaEdit, FaTrash, FaExclamationTriangle,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import ClusterService from '../../services/cluster.service';
import './SettingsLayout.css';

const PROVIDER_CHOICES = [
    ['kubernetes', 'Generic Kubernetes'],
    ['eks', 'AWS EKS'],
    ['gke', 'Google GKE'],
    ['aks', 'Azure AKS'],
    ['openshift', 'OpenShift'],
    ['rke', 'Rancher RKE'],
    ['kind', 'kind (local)'],
    ['minikube', 'Minikube (local)'],
    ['bare_metal', 'Bare metal / VM (no K8s)'],
    ['other', 'Other'],
];

const EMPTY_FORM = {
    name: '',
    description: '',
    provider: 'kubernetes',
    region: '',
    kubernetes_context: '',
    is_active: true,
};

const ClusterSettings = () => {
    const { t } = useTranslation();

    const [clusters, setClusters] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState(null);   // cluster row or null (create)
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);

    const [deleting, setDeleting] = useState(null);   // cluster row
    const [deleteBusy, setDeleteBusy] = useState(false);

    const load = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            setClusters(await ClusterService.list());
        } catch {
            setError(t('clusters.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [t]);

    useEffect(() => { load(); }, [load]);

    const openCreate = () => {
        setEditing(null);
        setForm(EMPTY_FORM);
        setShowForm(true);
    };

    const openEdit = (cluster) => {
        setEditing(cluster);
        setForm({
            name: cluster.name || '',
            description: cluster.description || '',
            provider: cluster.provider || 'kubernetes',
            region: cluster.region || '',
            kubernetes_context: cluster.kubernetes_context || '',
            is_active: cluster.is_active,
        });
        setShowForm(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const name = (form.name || '').trim();
        if (!name) return;
        try {
            setSaving(true);
            if (editing) {
                await ClusterService.update(editing.id, form);
                toast.success(t('clusters.updateSuccess'));
            } else {
                await ClusterService.create(form);
                toast.success(t('clusters.createSuccess'));
            }
            setShowForm(false);
            await load();
        } catch (err) {
            const detail = err?.response?.data?.name?.[0]
                || err?.response?.data?.detail
                || t('clusters.saveFailed');
            toast.error(detail);
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!deleting) return;
        try {
            setDeleteBusy(true);
            await ClusterService.delete(deleting.id);
            toast.success(t('clusters.deleteSuccess'));
            setDeleting(null);
            await load();
        } catch {
            toast.error(t('clusters.deleteFailed'));
        } finally {
            setDeleteBusy(false);
        }
    };

    return (
        <div className="settings-section">
            <PageHeader
                title={t('clusters.title')}
                subtitle={t('clusters.subtitle')}
                actions={
                    <Button variant="primary" onClick={openCreate}>
                        <FaPlus className="me-1" /> {t('clusters.new')}
                    </Button>
                }
            />

            {error && <Alert variant="danger">{error}</Alert>}

            {loading ? (
                <div className="text-center py-4">
                    <Spinner animation="border" size="sm" /> {t('common.loading')}
                </div>
            ) : clusters.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaServer size={40} className="mb-2 opacity-50" />
                    <p>{t('clusters.empty')}</p>
                    <p className="small">{t('clusters.emptyHint')}</p>
                </div>
            ) : (
                <Table hover responsive className="table-stack settings-table clusters-table">
                    <thead>
                        <tr>
                            <th>{t('clusters.name')}</th>
                            <th>{t('clusters.provider')}</th>
                            <th>{t('clusters.region')}</th>
                            <th>{t('clusters.integrations')}</th>
                            <th>{t('clusters.status')}</th>
                            <th style={{ width: 120 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {clusters.map((c) => (
                            <tr key={c.id} className={c.is_active ? '' : 'text-muted'}>
                                <td>
                                    <strong>{c.name}</strong>
                                    {c.description && (
                                        <div className="small text-muted">{c.description}</div>
                                    )}
                                </td>
                                <td>{c.provider_display}</td>
                                <td>{c.region || '—'}</td>
                                <td>{c.integration_count}</td>
                                <td>
                                    {c.is_active
                                        ? <Badge bg="success">{t('clusters.active')}</Badge>
                                        : <Badge bg="secondary">{t('clusters.inactive')}</Badge>}
                                </td>
                                <td>
                                    <Button
                                        variant="outline-secondary" size="sm"
                                        className="me-1"
                                        onClick={() => openEdit(c)}
                                        title={t('common.edit')}
                                    >
                                        <FaEdit />
                                    </Button>
                                    <Button
                                        variant="outline-danger" size="sm"
                                        onClick={() => setDeleting(c)}
                                        title={t('common.delete')}
                                    >
                                        <FaTrash />
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}

            {/* Create / Edit modal */}
            <Modal show={showForm} onHide={() => setShowForm(false)} centered>
                <Form onSubmit={handleSubmit}>
                    <Modal.Header closeButton>
                        <Modal.Title>
                            {editing ? t('clusters.edit') : t('clusters.new')}
                        </Modal.Title>
                    </Modal.Header>
                    <Modal.Body>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('clusters.name')}</Form.Label>
                            <Form.Control
                                type="text"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="prod-eks"
                                maxLength={100}
                                required
                                autoFocus
                            />
                            <Form.Text className="text-muted">
                                {t('clusters.nameHelp')}
                            </Form.Text>
                        </Form.Group>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('clusters.provider')}</Form.Label>
                            <Form.Select
                                value={form.provider}
                                onChange={(e) => setForm({ ...form, provider: e.target.value })}
                            >
                                {PROVIDER_CHOICES.map(([code, label]) => (
                                    <option key={code} value={code}>{label}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('clusters.region')}</Form.Label>
                            <Form.Control
                                type="text"
                                value={form.region}
                                onChange={(e) => setForm({ ...form, region: e.target.value })}
                                placeholder="us-west-2"
                                maxLength={64}
                            />
                        </Form.Group>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('clusters.context')}</Form.Label>
                            <Form.Control
                                type="text"
                                value={form.kubernetes_context}
                                onChange={(e) => setForm({ ...form, kubernetes_context: e.target.value })}
                                placeholder="arn:aws:eks:us-west-2:..."
                                maxLength={255}
                            />
                            <Form.Text className="text-muted">
                                {t('clusters.contextHelp')}
                            </Form.Text>
                        </Form.Group>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('clusters.description')}</Form.Label>
                            <Form.Control
                                as="textarea" rows={2}
                                value={form.description}
                                onChange={(e) => setForm({ ...form, description: e.target.value })}
                            />
                        </Form.Group>
                        <Form.Group>
                            <Form.Check
                                type="switch"
                                label={t('clusters.activeLabel')}
                                checked={form.is_active}
                                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                            />
                        </Form.Group>
                    </Modal.Body>
                    <Modal.Footer>
                        <Button variant="secondary" onClick={() => setShowForm(false)}>
                            {t('common.cancel')}
                        </Button>
                        <Button
                            variant="primary" type="submit"
                            disabled={saving || !form.name.trim()}
                        >
                            {saving
                                ? <><Spinner size="sm" animation="border" /> {t('common.saving')}</>
                                : t('common.save')}
                        </Button>
                    </Modal.Footer>
                </Form>
            </Modal>

            {/* Delete confirmation */}
            <Modal show={!!deleting} onHide={() => setDeleting(null)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>{t('clusters.deleteTitle')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>{t('clusters.deleteConfirm', { name: deleting?.name || '' })}</p>
                    {deleting?.integration_count > 0 && (
                        <Alert variant="warning" className="d-flex align-items-start">
                            <FaExclamationTriangle className="me-2 mt-1 flex-shrink-0" />
                            <span>
                                {t('clusters.deleteWarning', { count: deleting.integration_count })}
                            </span>
                        </Alert>
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setDeleting(null)}>
                        {t('common.cancel')}
                    </Button>
                    <Button variant="danger" onClick={handleDelete} disabled={deleteBusy}>
                        {deleteBusy
                            ? <><Spinner size="sm" animation="border" /> {t('common.deleting')}</>
                            : t('common.delete')}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default ClusterSettings;
