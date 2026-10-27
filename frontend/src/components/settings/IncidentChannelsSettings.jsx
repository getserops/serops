/**
 * IncidentChannelsSettings — manage outbound Slack / Teams / PagerDuty /
 * OpsGenie destinations for post-RCA notifications (Items #22 + #23).
 *
 * Under Settings → Incident Channels. Admin-only writes (backend
 * requires alerting.manage).
 *
 * Payload security: secrets (webhook_url / api_key) are write-only —
 * once set, the backend never returns the plaintext, only a
 * has_webhook_url / has_api_key boolean.
 */

import React, { useState, useEffect, useCallback } from 'react';
import PageHeader from '../PageHeader';
import { Button, Modal, Form, Spinner, Table, Alert, Badge } from 'react-bootstrap';
import {
    FaBell, FaPlus, FaEdit, FaTrash, FaCheckCircle, FaTimesCircle, FaPaperPlane,
    FaKey,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import IncidentChannelsService from '../../services/incidentChannels.service';
import { SettingsService } from '../../services/settings.service';
import './SettingsLayout.css';


/**
 * Q5-5 (2026-09-21): per-org alert-ingest secret rotation UI. Shown
 * next to the "New channel" button on the Delivery Channels page so
 * admins configuring outbound + inbound notification plumbing find
 * both surfaces in one place. Plaintext returned once on rotate;
 * the modal is the ONLY time it will ever be shown.
 */
const AlertIngestSecretButton = () => {
    const [status, setStatus] = React.useState(null);
    const [rotated, setRotated] = React.useState(null);   // plaintext once
    const [busy, setBusy] = React.useState(false);
    const [modalOpen, setModalOpen] = React.useState(false);

    const refresh = React.useCallback(async () => {
        try {
            const s = await SettingsService.getAlertIngestSecret();
            setStatus(s);
        } catch (e) {
            /* silent */
        }
    }, []);

    React.useEffect(() => { refresh(); }, [refresh]);

    const rotate = async () => {
        if (status?.has_secret && !window.confirm(
            'Rotating supersedes the current alert-ingest secret immediately. '
            + 'Existing Alertmanager / Grafana / Datadog webhooks will stop '
            + 'working until you paste the new token into them. Continue?'
        )) return;
        setBusy(true);
        try {
            const r = await SettingsService.rotateAlertIngestSecret();
            setRotated(r);
            setModalOpen(true);
            await refresh();
            toast.success('Alert-ingest secret rotated');
        } catch (e) {
            toast.error('Rotation failed');
        } finally {
            setBusy(false);
        }
    };

    return (
        <>
            <Button
                variant="outline-secondary"
                onClick={rotate}
                disabled={busy}
                aria-label={status?.has_secret
                    ? 'Rotate alert-ingest secret'
                    : 'Generate alert-ingest secret'}
                title={status?.has_secret
                    ? `Prefix: ${status.prefix}. Last rotated: ${status.rotated_at || 'never'}`
                    : 'Generate a per-org alert-ingest bearer secret'}
            >
                <FaKey className="me-1" aria-hidden="true" />
                {status?.has_secret ? 'Rotate ingest secret' : 'Generate ingest secret'}
            </Button>

            <Modal show={modalOpen} onHide={() => setModalOpen(false)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>Your new alert-ingest secret</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Alert variant="warning">
                        <strong>Copy this now.</strong> SerOps will never show it
                        again. Use it as the Bearer token in your Alertmanager /
                        Grafana / Datadog webhook Authorization header. Sentry
                        signs its webhooks instead: see the Real-time Alerts docs.
                    </Alert>
                    {rotated && (
                        <>
                            <Form.Label>Secret (plaintext)</Form.Label>
                            <Form.Control
                                as="textarea" rows={2} readOnly value={rotated.plaintext}
                                onFocus={(e) => e.target.select()}
                                className="ds-mono"
                            />
                            <p className="small mt-2 text-muted">
                                Rotated at {rotated.rotated_at}
                            </p>
                        </>
                    )}
                </Modal.Body>
                <Modal.Footer>
                    <Button
                        variant="secondary"
                        onClick={() => {
                            navigator.clipboard.writeText(rotated?.plaintext || '');
                            toast.info('Copied to clipboard');
                        }}
                    >
                        Copy
                    </Button>
                    <Button variant="primary" onClick={() => setModalOpen(false)}>
                        I've saved it
                    </Button>
                </Modal.Footer>
            </Modal>
        </>
    );
};

// PR-N phase 2 (2026-09-26): 'email' joins the delivery-target set so
// the settings surface matches the Grafana / Alertmanager pattern
// (one uniform table of destinations).
const KIND_CHOICES = [
    ['slack', 'Slack'],
    ['teams', 'Microsoft Teams'],
    ['pagerduty', 'PagerDuty'],
    ['opsgenie', 'OpsGenie'],
    ['email', 'Email'],
];
const TRIGGER_CHOICES = [
    ['batch_analyzed', 'Any batch analyzed'],
    ['alert_triggered', 'Alert-triggered batch analyzed'],
    ['critical_issue', 'Batch produced ≥1 critical issue'],
];
const SEVERITY_CHOICES = ['', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

const EMPTY_FORM = {
    name: '',
    kind: 'slack',
    webhook_url_input: '',
    api_key_input: '',
    extra_config: {},
    trigger_events: [],
    min_severity: '',
    is_active: true,
};

const IncidentChannelsSettings = () => {
    const { t } = useTranslation();

    const [channels, setChannels] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const [showForm, setShowForm] = useState(false);
    const [editing, setEditing] = useState(null);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);
    const [deleting, setDeleting] = useState(null);
    const [testingId, setTestingId] = useState(null);
    // Email recipients as typed; saved as extra_config.to (a list).
    const [recipientsText, setRecipientsText] = useState('');

    const load = useCallback(async () => {
        try {
            setLoading(true);
            setError(null);
            setChannels(await IncidentChannelsService.list());
        } catch {
            setError(t('incidentChannels.loadFailed'));
        } finally {
            setLoading(false);
        }
    }, [t]);

    useEffect(() => { load(); }, [load]);

    const openCreate = () => {
        setEditing(null);
        setForm(EMPTY_FORM);
        setRecipientsText('');
        setShowForm(true);
    };

    const openEdit = (channel) => {
        setEditing(channel);
        setForm({
            name: channel.name || '',
            kind: channel.kind,
            // Secrets are write-only from the backend — leave blank on edit
            // (empty = don't change). User must re-enter to rotate.
            webhook_url_input: '',
            api_key_input: '',
            extra_config: channel.extra_config || {},
            trigger_events: channel.trigger_events || [],
            min_severity: channel.min_severity || '',
            is_active: channel.is_active,
        });
        const to = channel.extra_config?.to;
        setRecipientsText(Array.isArray(to) ? to.join(', ') : (to || ''));
        setShowForm(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            setSaving(true);
            // Strip empty secret fields so we don't blank them on edit.
            const payload = { ...form };
            if (!payload.webhook_url_input) delete payload.webhook_url_input;
            if (!payload.api_key_input) delete payload.api_key_input;
            if (payload.kind === 'email') {
                payload.extra_config = {
                    ...payload.extra_config,
                    to: recipientsText.split(/[\s,;]+/).filter(Boolean),
                };
            }
            if (editing) {
                await IncidentChannelsService.update(editing.id, payload);
                toast.success(t('incidentChannels.updateSuccess'));
            } else {
                await IncidentChannelsService.create(payload);
                toast.success(t('incidentChannels.createSuccess'));
            }
            setShowForm(false);
            await load();
        } catch (err) {
            const data = err?.response?.data;
            const detail = data?.detail
                || Object.values(data || {})[0]
                || t('incidentChannels.saveFailed');
            toast.error(Array.isArray(detail) ? detail[0] : String(detail));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!deleting) return;
        try {
            await IncidentChannelsService.delete(deleting.id);
            toast.success(t('incidentChannels.deleteSuccess'));
            setDeleting(null);
            await load();
        } catch {
            toast.error(t('incidentChannels.deleteFailed'));
        }
    };

    const handleTest = async (channel) => {
        try {
            setTestingId(channel.id);
            const res = await IncidentChannelsService.testSend(channel.id);
            if (res.ok) {
                toast.success(t('incidentChannels.testSent'));
            } else {
                toast.error(t('incidentChannels.testFailed') + ': ' + (res.message || ''));
            }
            await load();
        } catch {
            toast.error(t('incidentChannels.testFailed'));
        } finally {
            setTestingId(null);
        }
    };

    const kindNeedsWebhook = ['slack', 'teams'].includes(form.kind);
    const kindNeedsApiKey = ['pagerduty', 'opsgenie'].includes(form.kind);

    return (
        <div className="settings-section">
            <PageHeader
                title={t('incidentChannels.title')}
                subtitle={t('incidentChannels.subtitle')}
                actions={
                    <div className="d-flex gap-2">
                        <AlertIngestSecretButton />
                        <Button variant="primary" onClick={openCreate}>
                            <FaPlus className="me-1" /> {t('incidentChannels.new')}
                        </Button>
                    </div>
                }
            />

            {error && <Alert variant="danger">{error}</Alert>}

            {loading ? (
                <div className="text-center py-4">
                    <Spinner animation="border" size="sm" /> {t('common.loading')}
                </div>
            ) : channels.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaBell size={40} className="mb-2 opacity-50" />
                    <p>{t('incidentChannels.empty')}</p>
                </div>
            ) : (
                <Table hover responsive className="table-stack settings-table channels-table">
                    <thead>
                        <tr>
                            <th>{t('incidentChannels.name')}</th>
                            <th>{t('incidentChannels.kind')}</th>
                            <th>{t('incidentChannels.triggers')}</th>
                            <th>{t('incidentChannels.minSeverity')}</th>
                            <th>{t('incidentChannels.status')}</th>
                            <th>{t('incidentChannels.lastSend')}</th>
                            <th style={{ width: 180 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {channels.map((c) => (
                            <tr key={c.id} className={c.is_active ? '' : 'text-muted'}>
                                <td data-label={t('incidentChannels.name')}>
                                    <strong>{c.name}</strong>
                                    {c.last_error && (
                                        <div className="small text-danger">
                                            <FaTimesCircle size={10} className="me-1" />
                                            {c.last_error.slice(0, 80)}
                                        </div>
                                    )}
                                </td>
                                <td data-label={t('incidentChannels.kind')}>{c.kind_display}</td>
                                <td data-label={t('incidentChannels.triggers')}>
                                    {(c.trigger_events || []).length === 0
                                        ? <span className="text-muted small">any</span>
                                        : c.trigger_events.map((t) => (
                                            <Badge bg="light" text="dark" key={t} className="me-1">
                                                {t}
                                            </Badge>
                                        ))}
                                </td>
                                <td data-label={t('incidentChannels.minSeverity')}>{c.min_severity || <span className="text-muted small">any</span>}</td>
                                <td data-label={t('incidentChannels.status')}>
                                    {c.is_active
                                        ? <Badge bg="success">{t('common.active') || 'Active'}</Badge>
                                        : <Badge bg="secondary">{t('common.inactive') || 'Inactive'}</Badge>}
                                </td>
                                <td data-label={t('incidentChannels.lastSend')} className="small text-muted">
                                    {c.last_sent_at
                                        ? new Date(c.last_sent_at).toLocaleString()
                                        : '—'}
                                </td>
                                <td>
                                    <Button
                                        variant="outline-secondary" size="sm" className="me-1"
                                        onClick={() => handleTest(c)}
                                        disabled={testingId === c.id}
                                        title={t('incidentChannels.test')}
                                    >
                                        {testingId === c.id
                                            ? <Spinner size="sm" animation="border" />
                                            : <FaPaperPlane />}
                                    </Button>
                                    <Button
                                        variant="outline-secondary" size="sm" className="me-1"
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

            {/* Create / edit modal */}
            <Modal show={showForm} onHide={() => setShowForm(false)} centered size="lg">
                <Form onSubmit={handleSubmit}>
                    <Modal.Header closeButton>
                        <Modal.Title>
                            {editing ? t('incidentChannels.edit') : t('incidentChannels.new')}
                        </Modal.Title>
                    </Modal.Header>
                    <Modal.Body>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('incidentChannels.name')}</Form.Label>
                            <Form.Control
                                type="text"
                                value={form.name}
                                onChange={(e) => setForm({ ...form, name: e.target.value })}
                                placeholder="SRE Slack"
                                required
                            />
                        </Form.Group>
                        <Form.Group className="mb-3">
                            <Form.Label>{t('incidentChannels.kind')}</Form.Label>
                            <Form.Select
                                value={form.kind}
                                onChange={(e) => setForm({ ...form, kind: e.target.value })}
                                disabled={!!editing}
                            >
                                {KIND_CHOICES.map(([code, label]) => (
                                    <option key={code} value={code}>{label}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>

                        {kindNeedsWebhook && (
                            <Form.Group className="mb-3">
                                <Form.Label>{t('incidentChannels.webhookUrl')}</Form.Label>
                                <Form.Control
                                    type="password"
                                    autoComplete="new-password"
                                    value={form.webhook_url_input}
                                    onChange={(e) => setForm({ ...form, webhook_url_input: e.target.value })}
                                    placeholder={editing?.has_webhook_url
                                        ? t('incidentChannels.leaveBlankUnchanged')
                                        : 'https://hooks.slack.com/services/...'}
                                    required={!editing}
                                />
                                <Form.Text className="text-muted">
                                    {editing?.has_webhook_url && t('incidentChannels.currentStored')}
                                </Form.Text>
                            </Form.Group>
                        )}

                        {kindNeedsApiKey && (
                            <>
                                <Form.Group className="mb-3">
                                    <Form.Label>{t('incidentChannels.apiKey')}</Form.Label>
                                    <Form.Control
                                        type="password"
                                        autoComplete="new-password"
                                        value={form.api_key_input}
                                        onChange={(e) => setForm({ ...form, api_key_input: e.target.value })}
                                        placeholder={editing?.has_api_key
                                            ? t('incidentChannels.leaveBlankUnchanged')
                                            : (form.kind === 'pagerduty'
                                                ? 'Events API v2 integration key'
                                                : 'OpsGenie API key')}
                                        required={!editing}
                                    />
                                </Form.Group>
                                {form.kind === 'opsgenie' && (
                                    <Form.Group className="mb-3">
                                        <Form.Label>{t('incidentChannels.region')}</Form.Label>
                                        <Form.Select
                                            value={form.extra_config?.region || 'us'}
                                            onChange={(e) => setForm({
                                                ...form,
                                                extra_config: { ...form.extra_config, region: e.target.value },
                                            })}
                                        >
                                            <option value="us">us</option>
                                            <option value="eu">eu</option>
                                        </Form.Select>
                                    </Form.Group>
                                )}
                            </>
                        )}

                        {form.kind === 'email' && (
                            // The email sender reads extra_config.to; without this field an
                            // Email channel had no recipients and every send failed.
                            <Form.Group className="mb-3" controlId="channel-recipients">
                                <Form.Label>{t('incidentChannels.recipients')}</Form.Label>
                                <Form.Control
                                    type="text"
                                    value={recipientsText}
                                    onChange={(e) => setRecipientsText(e.target.value)}
                                    placeholder="sre@example.com, oncall@example.com"
                                    required
                                />
                                <Form.Text className="text-muted">{t('incidentChannels.recipientsHint')}</Form.Text>
                            </Form.Group>
                        )}

                        <Form.Group className="mb-3">
                            <Form.Label>{t('incidentChannels.triggers')}</Form.Label>
                            {TRIGGER_CHOICES.map(([code, label]) => (
                                <Form.Check
                                    key={code}
                                    type="checkbox"
                                    id={`trig-${code}`}
                                    label={label}
                                    checked={form.trigger_events.includes(code)}
                                    onChange={(e) => {
                                        const next = e.target.checked
                                            ? [...form.trigger_events, code]
                                            : form.trigger_events.filter((t) => t !== code);
                                        setForm({ ...form, trigger_events: next });
                                    }}
                                />
                            ))}
                            <Form.Text className="text-muted">
                                {t('incidentChannels.triggersHelp')}
                            </Form.Text>
                        </Form.Group>

                        <Form.Group className="mb-3">
                            <Form.Label>{t('incidentChannels.minSeverity')}</Form.Label>
                            <Form.Select
                                value={form.min_severity}
                                onChange={(e) => setForm({ ...form, min_severity: e.target.value })}
                            >
                                {SEVERITY_CHOICES.map((s) => (
                                    <option key={s || 'any'} value={s}>{s || 'any'}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>

                        <Form.Group>
                            <Form.Check
                                type="switch"
                                label={t('common.active') || 'Active'}
                                checked={form.is_active}
                                onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                            />
                        </Form.Group>
                    </Modal.Body>
                    <Modal.Footer>
                        <Button variant="secondary" onClick={() => setShowForm(false)}>
                            {t('common.cancel')}
                        </Button>
                        <Button variant="primary" type="submit" disabled={saving || !form.name.trim()}>
                            {saving
                                ? <><Spinner size="sm" animation="border" /> {t('common.saving')}</>
                                : t('common.save')}
                        </Button>
                    </Modal.Footer>
                </Form>
            </Modal>

            <Modal show={!!deleting} onHide={() => setDeleting(null)} centered>
                <Modal.Header closeButton>
                    <Modal.Title>{t('incidentChannels.deleteTitle')}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    {t('incidentChannels.deleteConfirm', { name: deleting?.name || '' })}
                </Modal.Body>
                <Modal.Footer>
                    <Button variant="secondary" onClick={() => setDeleting(null)}>
                        {t('common.cancel')}
                    </Button>
                    <Button variant="danger" onClick={handleDelete}>
                        {t('common.delete')}
                    </Button>
                </Modal.Footer>
            </Modal>
        </div>
    );
};

export default IncidentChannelsSettings;
