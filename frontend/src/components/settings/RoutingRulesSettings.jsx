/**
 * RoutingRulesSettings — PR-N phase 2 (2026-09-26).
 *
 * Grafana / Alertmanager-style route table. Each rule declares a
 * matcher (severity + envs + services + event types) and a set of
 * target Delivery Channels. Dispatcher walks every active rule ->
 * union of matching targets -> dedup -> send.
 *
 * Under Settings -> Routing Rules. Admin-only writes (backend
 * requires alerting.manage).
 */

import React, { useState, useEffect, useCallback } from 'react';
import PageHeader from '../PageHeader';
import { Button, Modal, Form, Spinner, Table, Alert, Badge } from 'react-bootstrap';
import { FaPlus, FaEdit, FaTrash } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { SettingsService } from '../../services/settings.service';
import './SettingsLayout.css';

const SEVERITY_CHOICES = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
const EVENT_CHOICES = [
    ['batch_analyzed', 'Any batch analysed'],
    ['alert_triggered', 'Alert-triggered'],
    ['critical_issue', 'Critical issue produced'],
];

const emptyRule = {
    name: '',
    is_active: true,
    min_severity: '',
    environments: [],
    services: [],
    event_types: [],
    target_ids: [],
    priority: 100,
};

const csvToList = (s) =>
    (s || '')
        .split(',')
        .map((x) => x.trim())
        .filter(Boolean);

const listToCsv = (a) => (a || []).join(', ');

const RoutingRulesSettings = () => {
    const [rules, setRules] = useState([]);
    const [channels, setChannels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [editing, setEditing] = useState(null);
    const [form, setForm] = useState(emptyRule);
    const [saving, setSaving] = useState(false);

    const refresh = useCallback(async () => {
        setLoading(true);
        try {
            const [rulesData, channelsData] = await Promise.all([
                SettingsService.listRoutingRules(),
                SettingsService.listDeliveryChannels(),
            ]);
            setRules(rulesData || []);
            setChannels(channelsData || []);
        } catch (e) {
            toast.error('Failed to load routing rules');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    const openCreate = () => {
        setEditing(null);
        setForm(emptyRule);
        setShowModal(true);
    };

    const openEdit = (rule) => {
        setEditing(rule);
        setForm({
            name: rule.name || '',
            is_active: rule.is_active,
            min_severity: rule.min_severity || '',
            environments: rule.environments || [],
            services: rule.services || [],
            event_types: rule.event_types || [],
            target_ids: rule.target_ids
                || (rule.targets ? rule.targets.map((t) => t.id || t) : []),
            priority: rule.priority ?? 100,
        });
        setShowModal(true);
    };

    const handleSave = async () => {
        if (!form.name.trim()) {
            toast.warn('Rule name is required');
            return;
        }
        setSaving(true);
        try {
            if (editing) {
                await SettingsService.updateRoutingRule(editing.id, form);
                toast.success('Rule updated');
            } else {
                await SettingsService.createRoutingRule(form);
                toast.success('Rule created');
            }
            setShowModal(false);
            await refresh();
        } catch (e) {
            const msg = e?.response?.data
                ? JSON.stringify(e.response.data)
                : e.message;
            toast.error(`Save failed: ${msg}`);
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (rule) => {
        if (!window.confirm(`Delete routing rule "${rule.name}"?`)) return;
        try {
            await SettingsService.deleteRoutingRule(rule.id);
            toast.success('Rule deleted');
            await refresh();
        } catch (e) {
            toast.error('Delete failed');
        }
    };

    const channelName = (id) => {
        const c = channels.find((x) => x.id === id);
        return c ? `${c.name} (${c.kind})` : `#${id}`;
    };

    return (
        <div className="settings-content">
            <PageHeader
                title="Routing Rules"
                subtitle="Rules decide which delivery channels get notified for each incident. Every active rule that matches contributes its targets; a channel that matches multiple rules is contacted once."
                actions={
                    <Button
                        variant="primary"
                        onClick={openCreate}
                        aria-label="Add a new routing rule"
                    >
                        <FaPlus className="me-1" aria-hidden="true" /> New rule
                    </Button>
                }
            />

            {loading ? (
                <div className="text-center py-4">
                    <Spinner animation="border" size="sm" /> Loading…
                </div>
            ) : rules.length === 0 ? (
                <div className="ds-card text-center text-muted py-5 px-3">
                    No routing rules yet. Create one to route incidents to your
                    Delivery Channels.
                </div>
            ) : (
                <Table hover responsive size="sm" className="table-stack settings-table routing-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Match</th>
                            <th>Targets</th>
                            <th>Priority</th>
                            <th>Active</th>
                            <th style={{ width: 100 }}></th>
                        </tr>
                    </thead>
                    <tbody>
                        {rules.map((r) => (
                            <tr key={r.id}>
                                <td>{r.name}</td>
                                <td>
                                    {r.min_severity && (
                                        <Badge bg="danger" className="me-1">
                                            ≥ {r.min_severity}
                                        </Badge>
                                    )}
                                    {(r.event_types || []).map((t) => (
                                        <Badge key={t} bg="secondary" className="me-1">
                                            {t}
                                        </Badge>
                                    ))}
                                    {(r.environments || []).map((e) => (
                                        <Badge key={e} bg="info" className="me-1">
                                            env: {e}
                                        </Badge>
                                    ))}
                                    {(r.services || []).map((s) => (
                                        <Badge key={s} bg="light" text="dark" className="me-1">
                                            svc: {s}
                                        </Badge>
                                    ))}
                                    {!r.min_severity
                                        && (!r.event_types || r.event_types.length === 0)
                                        && (!r.environments || r.environments.length === 0)
                                        && (!r.services || r.services.length === 0)
                                        && <span className="text-muted">any incident</span>}
                                </td>
                                <td>
                                    {((r.target_ids || (r.targets || []).map((t) => t.id || t))
                                        || []
                                    ).map((id) => (
                                        <div key={id} className="small">
                                            {channelName(id)}
                                        </div>
                                    ))}
                                </td>
                                <td>{r.priority ?? 100}</td>
                                <td>
                                    {r.is_active
                                        ? <Badge bg="success">Yes</Badge>
                                        : <Badge bg="secondary">No</Badge>}
                                </td>
                                <td>
                                    <Button
                                        variant="link"
                                        size="sm"
                                        onClick={() => openEdit(r)}
                                        aria-label={`Edit rule ${r.name}`}
                                    >
                                        <FaEdit aria-hidden="true" />
                                    </Button>
                                    <Button
                                        variant="link"
                                        size="sm"
                                        className="text-danger"
                                        onClick={() => handleDelete(r)}
                                        aria-label={`Delete rule ${r.name}`}
                                    >
                                        <FaTrash aria-hidden="true" />
                                    </Button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
            )}

            <Modal show={showModal} onHide={() => setShowModal(false)} size="lg">
                <Modal.Header closeButton>
                    <Modal.Title>{editing ? 'Edit routing rule' : 'New routing rule'}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form>
                        <Form.Group className="mb-3">
                            <Form.Label>Name</Form.Label>
                            <Form.Control
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="e.g. SRE — prod criticals"
                            />
                        </Form.Group>

                        <div className="row">
                            <Form.Group className="mb-3 col-md-6">
                                <Form.Label>Min severity</Form.Label>
                                <Form.Select
                                    value={form.min_severity}
                                    onChange={(e) => setForm({ ...form, min_severity: e.target.value })}
                                    aria-label="Minimum severity floor"
                                >
                                    {SEVERITY_CHOICES.map((s) => (
                                        <option key={s} value={s}>{s || 'any severity'}</option>
                                    ))}
                                </Form.Select>
                            </Form.Group>

                            <Form.Group className="mb-3 col-md-6">
                                <Form.Label>Priority</Form.Label>
                                <Form.Control
                                    type="number"
                                    value={form.priority}
                                    onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value || 100, 10) })}
                                />
                                <Form.Text muted>Lower = evaluated earlier (informational).</Form.Text>
                            </Form.Group>
                        </div>

                        <Form.Group className="mb-3">
                            <Form.Label>Event types</Form.Label>
                            {EVENT_CHOICES.map(([code, label]) => (
                                <Form.Check
                                    key={code}
                                    type="checkbox"
                                    id={`event-${code}`}
                                    label={label}
                                    checked={form.event_types.includes(code)}
                                    onChange={(e) => {
                                        const next = new Set(form.event_types);
                                        if (e.target.checked) next.add(code);
                                        else next.delete(code);
                                        setForm({ ...form, event_types: Array.from(next) });
                                    }}
                                />
                            ))}
                            <Form.Text muted>Empty = every event.</Form.Text>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>Environments (comma-separated)</Form.Label>
                            <Form.Control
                                value={listToCsv(form.environments)}
                                onChange={(e) => setForm({ ...form, environments: csvToList(e.target.value) })}
                                placeholder="production, staging"
                            />
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>Services (comma-separated)</Form.Label>
                            <Form.Control
                                value={listToCsv(form.services)}
                                onChange={(e) => setForm({ ...form, services: csvToList(e.target.value) })}
                                placeholder="checkout, billing"
                            />
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>Target channels</Form.Label>
                            {channels.length === 0 ? (
                                <Alert variant="warning" className="small">
                                    No delivery channels configured yet. Create one under
                                    Settings → Delivery Channels first.
                                </Alert>
                            ) : (
                                channels.map((c) => (
                                    <Form.Check
                                        key={c.id}
                                        type="checkbox"
                                        id={`target-${c.id}`}
                                        label={`${c.name} (${c.kind})`}
                                        checked={form.target_ids.includes(c.id)}
                                        onChange={(e) => {
                                            const next = new Set(form.target_ids);
                                            if (e.target.checked) next.add(c.id);
                                            else next.delete(c.id);
                                            setForm({ ...form, target_ids: Array.from(next) });
                                        }}
                                    />
                                ))
                            )}
                        </Form.Group>

                        <Form.Check
                            type="switch"
                            id="rule-active"
                            label="Active"
                            checked={form.is_active}
                            onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                        />
                    </Form>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowModal(false)}>
                        Cancel
                    </Button>
                    <Button variant="primary" onClick={handleSave} disabled={saving}>
                        {saving ? <Spinner animation="border" size="sm" /> : 'Save rule'}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default RoutingRulesSettings;
