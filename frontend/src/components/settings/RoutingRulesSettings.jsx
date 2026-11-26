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
import { useTranslation } from 'react-i18next';
import { Button, Modal, Form, Spinner, Table, Alert, Badge } from 'react-bootstrap';
import { FaPlus, FaEdit, FaTrash } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { SettingsService } from '../../services/settings.service';
import { FLOOR_CHOICES, floorChoice, floorToSave } from '../../utils/severityFloor';
import { severityLabel } from '../../utils/severityLabel';
import './SettingsLayout.css';

const EVENT_CHOICES = [
    ['batch_analyzed', 'settings.routing.eventAnyBatch'],
    ['alert_triggered', 'settings.routing.eventAlertTriggered'],
    ['critical_issue', 'settings.routing.eventCriticalIssue'],
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
    const { t } = useTranslation();
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
            toast.error(t('settings.routing.loadFailed'));
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
            min_severity: floorChoice(rule.min_severity),
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
            toast.warn(t('settings.routing.nameRequired'));
            return;
        }
        setSaving(true);
        const payload = { ...form, min_severity: floorToSave(form.min_severity) };
        try {
            if (editing) {
                await SettingsService.updateRoutingRule(editing.id, payload);
                toast.success(t('settings.routing.ruleUpdated'));
            } else {
                await SettingsService.createRoutingRule(payload);
                toast.success(t('settings.routing.ruleCreated'));
            }
            setShowModal(false);
            await refresh();
        } catch (e) {
            const msg = e?.response?.data
                ? JSON.stringify(e.response.data)
                : e.message;
            toast.error(t('settings.routing.saveFailed', { message: msg }));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (rule) => {
        if (!window.confirm(t('settings.routing.deleteConfirm', { name: rule.name }))) return;
        try {
            await SettingsService.deleteRoutingRule(rule.id);
            toast.success(t('settings.routing.ruleDeleted'));
            await refresh();
        } catch (e) {
            toast.error(t('settings.routing.deleteFailed'));
        }
    };

    const channelName = (id) => {
        const c = channels.find((x) => x.id === id);
        return c ? `${c.name} (${c.kind})` : `#${id}`;
    };

    return (
        <div className="settings-content">
            <PageHeader
                title={t('nav.alertsRouting')}
                subtitle={t('settings.routing.subtitle')}
                actions={
                    <Button
                        variant="primary"
                        onClick={openCreate}
                        aria-label={t('settings.routing.addRuleAria')}
                    >
                        <FaPlus className="me-1" aria-hidden="true" /> {t('settings.routing.newRule')}
                    </Button>
                }
            />

            {loading ? (
                <div className="text-center py-4">
                    <Spinner animation="border" size="sm" /> {t('settings.routing.loading')}
                </div>
            ) : rules.length === 0 ? (
                <div className="ds-card text-center text-muted py-5 px-3">
                    {t('settings.routing.empty')}
                </div>
            ) : (
                <Table hover responsive size="sm" className="table-stack settings-table routing-table">
                    <thead>
                        <tr>
                            <th>{t('settings.routing.colName')}</th>
                            <th>{t('settings.routing.colMatch')}</th>
                            <th>{t('settings.routing.colTargets')}</th>
                            <th>{t('settings.routing.priority')}</th>
                            <th>{t('settings.routing.active')}</th>
                            <th style={{ width: 100 }}></th>
                        </tr>
                    </thead>
                    <tbody>
                        {rules.map((r) => (
                            <tr key={r.id}>
                                <td>{r.name}</td>
                                <td>
                                    {floorChoice(r.min_severity) && (
                                        <Badge bg="danger" className="me-1">
                                            ≥ {severityLabel(t, floorChoice(r.min_severity))}
                                        </Badge>
                                    )}
                                    {(r.event_types || []).map((t) => (
                                        <Badge key={t} bg="secondary" className="me-1">
                                            {t}
                                        </Badge>
                                    ))}
                                    {(r.environments || []).map((e) => (
                                        <Badge key={e} bg="info" className="me-1">
                                            {t('settings.routing.envBadge', { value: e })}
                                        </Badge>
                                    ))}
                                    {(r.services || []).map((s) => (
                                        <Badge key={s} bg="light" text="dark" className="me-1">
                                            {t('settings.routing.svcBadge', { value: s })}
                                        </Badge>
                                    ))}
                                    {!floorChoice(r.min_severity)
                                        && (!r.event_types || r.event_types.length === 0)
                                        && (!r.environments || r.environments.length === 0)
                                        && (!r.services || r.services.length === 0)
                                        && <span className="text-muted">{t('settings.routing.anyIncident')}</span>}
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
                                        ? <Badge bg="success">{t('common.yes')}</Badge>
                                        : <Badge bg="secondary">{t('common.no')}</Badge>}
                                </td>
                                <td>
                                    <Button
                                        variant="link"
                                        size="sm"
                                        onClick={() => openEdit(r)}
                                        aria-label={t('settings.routing.editRuleAria', { name: r.name })}
                                    >
                                        <FaEdit aria-hidden="true" />
                                    </Button>
                                    <Button
                                        variant="link"
                                        size="sm"
                                        className="text-danger"
                                        onClick={() => handleDelete(r)}
                                        aria-label={t('settings.routing.deleteRuleAria', { name: r.name })}
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
                    <Modal.Title>{editing ? t('settings.routing.editTitle') : t('settings.routing.newTitle')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('settings.routing.name')}</Form.Label>
                            <Form.Control
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder={t('settings.routing.namePlaceholder')}
                            />
                        </Form.Group>

                        <div className="row">
                            <Form.Group className="mb-3 col-md-6">
                                <Form.Label>{t('settings.routing.minSeverity')}</Form.Label>
                                <Form.Select
                                    value={form.min_severity}
                                    onChange={(e) => setForm({ ...form, min_severity: e.target.value })}
                                    aria-label={t('settings.routing.minSeverityAria')}
                                >
                                    {FLOOR_CHOICES.map((s) => (
                                        <option key={s || 'any'} value={s}>{s ? severityLabel(t, s) : t('settings.routing.anySeverity')}</option>
                                    ))}
                                </Form.Select>
                            </Form.Group>

                            <Form.Group className="mb-3 col-md-6">
                                <Form.Label>{t('settings.routing.priority')}</Form.Label>
                                <Form.Control
                                    type="number"
                                    value={form.priority}
                                    onChange={(e) => setForm({ ...form, priority: parseInt(e.target.value || 100, 10) })}
                                />
                                <Form.Text muted>{t('settings.routing.priorityHelp')}</Form.Text>
                            </Form.Group>
                        </div>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('settings.routing.eventTypes')}</Form.Label>
                            {EVENT_CHOICES.map(([code, label]) => (
                                <Form.Check
                                    key={code}
                                    type="checkbox"
                                    id={`event-${code}`}
                                    label={t(label)}
                                    checked={form.event_types.includes(code)}
                                    onChange={(e) => {
                                        const next = new Set(form.event_types);
                                        if (e.target.checked) next.add(code);
                                        else next.delete(code);
                                        setForm({ ...form, event_types: Array.from(next) });
                                    }}
                                />
                            ))}
                            <Form.Text muted>{t('settings.routing.eventTypesHelp')}</Form.Text>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('settings.routing.environments')}</Form.Label>
                            <Form.Control
                                value={listToCsv(form.environments)}
                                onChange={(e) => setForm({ ...form, environments: csvToList(e.target.value) })}
                                placeholder="production, staging"
                            />
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('settings.routing.services')}</Form.Label>
                            <Form.Control
                                value={listToCsv(form.services)}
                                onChange={(e) => setForm({ ...form, services: csvToList(e.target.value) })}
                                placeholder="checkout, billing"
                            />
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('settings.routing.targetChannels')}</Form.Label>
                            {channels.length === 0 ? (
                                <Alert variant="warning" className="small">
                                    {t('settings.routing.noChannels')}
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
                            label={t('settings.routing.active')}
                            checked={form.is_active}
                            onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                        />
                    </Form>
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setShowModal(false)}>
                        {t('common.cancel')}
                    </Button>
                    <Button variant="primary" onClick={handleSave} disabled={saving}>
                        {saving ? <Spinner animation="border" size="sm" /> : t('settings.routing.saveRule')}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default RoutingRulesSettings;
