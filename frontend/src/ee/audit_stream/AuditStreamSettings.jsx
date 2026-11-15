/**
 * Settings → Audit Streaming (Enterprise, feature audit_streaming).
 *
 * The organisation's destinations (HTTPS collectors and syslog servers),
 * their delivery state, a test button, and the form to add or change one.
 * Secrets are write-only: the API says whether one is set, never its value.
 * Without the license the destinations are listed, and can be turned off
 * or removed, not added or changed.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Badge, Button, Form, Modal, Spinner, Table } from 'react-bootstrap';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { toast } from 'react-toastify';
import apiClient from '../../services/api-client';
import { usePermissions } from '../../utils/permissions';
import PageHeader from '../../components/PageHeader';
import ChoiceGroup from '../../components/settings/ChoiceGroup';
import '../../components/settings/SettingsLayout.css';

const URL = '/ee/audit-streams/';
const PORTS = { tls: 6514, tcp: 514, udp: 514 };
const EMPTY = {
    id: null, name: '', kind: 'http', enabled: true, url: '', http_format: 'json', auth_header_name: '',
    auth_header_value: '', signing_secret: '', host: '', port: 6514, transport: 'tls', ca_certificate: '',
};
const day = (iso) => (iso ? iso.slice(0, 16).replace('T', ' ') : '');

export const stateOf = (d) => {
    if (!d.enabled) return 'off';
    if (d.last_failure_at && (!d.last_success_at || d.last_failure_at > d.last_success_at)) return 'failing';
    return d.last_success_at ? 'healthy' : 'waiting';
};
const BADGE = { healthy: 'success', failing: 'danger', waiting: 'secondary', off: 'secondary' };

/** What to send: only the fields of the kind, secrets only when typed (or cleared). */
export const payloadOf = (form, original) => {
    const common = { name: form.name.trim(), enabled: form.enabled };
    if (!original) common.kind = form.kind;
    if (form.kind === 'http') {
        const p = { ...common, url: form.url.trim(), http_format: form.http_format, auth_header_name: form.auth_header_name.trim(),
            ca_certificate: form.ca_certificate };
        if (form.auth_header_value || form.clear_auth) p.auth_header_value = form.clear_auth ? '' : form.auth_header_value;
        if (form.signing_secret || form.clear_signing) p.signing_secret = form.clear_signing ? '' : form.signing_secret;
        return p;
    }
    return { ...common, host: form.host.trim(), port: Number(form.port) || PORTS[form.transport],
        transport: form.transport, ca_certificate: form.ca_certificate };
};

const AuditStreamSettings = () => {
    const { t } = useTranslation();
    const can = usePermissions();
    const canManage = can('settings.manage');
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const [editing, setEditing] = useState(null);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(null);

    const load = useCallback(() => apiClient.get(URL)
        .then((res) => { setData(res.data); setError(null); })
        .catch(() => setError(t('ee.auditStream.loadFailed'))), [t]);
    useEffect(() => { load(); }, [load]);

    const save = async () => {
        setSaving(true);
        try {
            const body = payloadOf(editing, editing.id ? data.destinations.find((d) => d.id === editing.id) : null);
            if (editing.id) await apiClient.put(`${URL}${editing.id}/`, body);
            else await apiClient.post(URL, body);
            setEditing(null);
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('ee.auditStream.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const toggle = async (d) => {
        try {
            await apiClient.put(`${URL}${d.id}/`, { enabled: !d.enabled });
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('ee.auditStream.saveFailed'));
        }
    };

    const remove = async (d) => {
        if (!window.confirm(t('ee.auditStream.removeConfirm', { name: d.name }))) return;
        try {
            await apiClient.delete(`${URL}${d.id}/`);
            await load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('ee.auditStream.saveFailed'));
        }
    };

    const test = async (d) => {
        setTesting(d.id);
        try {
            const res = await apiClient.post(`${URL}${d.id}/test/`);
            if (res.data.ok) toast.success(t('ee.auditStream.testOk'));
            else toast.error(t('ee.auditStream.testFailed', { error: res.data.error }));
        } catch (err) {
            toast.error(t('ee.auditStream.testFailed', { error: err?.response?.data?.error || err.message }));
        } finally {
            setTesting(null);
            load();
        }
    };

    if (error) return <div className="settings-section"><p className="form-hint">{error}</p></div>;
    if (!data) return <div className="settings-section text-center py-5"><Spinner animation="border" /></div>;

    const licensed = data.licensed;
    const set = (patch) => setEditing((prev) => ({ ...prev, ...patch }));
    const original = editing?.id ? data.destinations.find((d) => d.id === editing.id) : null;

    return (
        <div className="settings-section audit-stream-settings">
            <PageHeader
                title={t('ee.auditStream.title')}
                subtitle={t('ee.auditStream.subtitle')}
                actions={canManage && licensed && (
                    <button className="btn btn-primary" onClick={() => setEditing({ ...EMPTY })}>{t('ee.auditStream.add')}</button>
                )}
            />
            {!licensed && (
                <div className="alert alert-info small" role="note">
                    {t('ee.auditStream.unlicensed')}{' '}
                    {can('license.manage') && <Link to="/dash/settings/license">{t('ee.auditStream.licenseLink')}</Link>}
                </div>
            )}

            {data.destinations.length === 0 ? (
                <p className="form-hint">{t('ee.auditStream.empty')}</p>
            ) : (
                <Table hover responsive size="sm" className="table-stack settings-table audit-stream-table">
                    <thead>
                        <tr>
                            <th>{t('ee.auditStream.name')}</th>
                            <th>{t('ee.auditStream.kind')}</th>
                            <th>{t('ee.auditStream.status')}</th>
                            <th aria-label={t('ee.auditStream.edit')} />
                        </tr>
                    </thead>
                    <tbody>
                        {data.destinations.map((d) => {
                            const state = stateOf(d);
                            return (
                                <tr key={d.id}>
                                    <td>
                                        <strong>{d.name}</strong>
                                        <div className="small text-muted"><code>{d.target}</code></div>
                                    </td>
                                    <td>{d.kind === 'http' ? t('ee.auditStream.kindHttp') : t('ee.auditStream.kindSyslog')}</td>
                                    <td>
                                        <Badge bg={BADGE[state]}>{t(`ee.auditStream.${state}`)}</Badge>
                                        <div className="small text-muted">
                                            {t('ee.auditStream.delivered', { count: d.delivered_count })}
                                            {d.pending > 0 && <> · {t('ee.auditStream.pending', { count: d.pending })}</>}
                                        </div>
                                        {d.last_success_at && (
                                            <div className="small text-muted">{t('ee.auditStream.lastSuccess', { date: day(d.last_success_at) })}</div>
                                        )}
                                        {state === 'failing' && d.last_error && (
                                            <div className="small text-danger">{t('ee.auditStream.lastError', { error: d.last_error })}</div>
                                        )}
                                    </td>
                                    <td className="text-nowrap">
                                        {canManage && licensed && (
                                            <>
                                                <Button variant="outline-secondary" size="sm" className="me-1"
                                                    disabled={testing === d.id} onClick={() => test(d)}>{t('ee.auditStream.test')}</Button>
                                                <Button variant="outline-secondary" size="sm" className="me-1"
                                                    onClick={() => setEditing({ ...EMPTY, ...d, auth_header_value: '', signing_secret: '' })}>
                                                    {t('ee.auditStream.edit')}
                                                </Button>
                                            </>
                                        )}
                                        {canManage && d.enabled && !licensed && (
                                            <Button variant="outline-secondary" size="sm" className="me-1" onClick={() => toggle(d)}>
                                                {t('ee.auditStream.off')}
                                            </Button>
                                        )}
                                        {canManage && (
                                            <Button variant="outline-danger" size="sm" onClick={() => remove(d)}>{t('ee.auditStream.remove')}</Button>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </Table>
            )}
            <p className="form-hint">{t('ee.auditStream.guarantee')}</p>

            <Modal show={!!editing} onHide={() => setEditing(null)} size="lg">
                {editing && (
                    <>
                        <Modal.Header closeButton>
                            <Modal.Title>{editing.id ? editing.name : t('ee.auditStream.add')}</Modal.Title>
                        </Modal.Header>
                        <Modal.Body>
                            <Form.Group className="mb-3" controlId="stream-name">
                                <Form.Label>{t('ee.auditStream.name')}</Form.Label>
                                <Form.Control value={editing.name} maxLength={100} onChange={(e) => set({ name: e.target.value })} />
                            </Form.Group>
                            {!editing.id && (
                                <ChoiceGroup
                                    label={t('ee.auditStream.kind')}
                                    variant="cards"
                                    value={editing.kind}
                                    onChange={(kind) => set({ kind })}
                                    options={[
                                        { value: 'http', label: t('ee.auditStream.kindHttp'), description: t('ee.auditStream.kindHttpDesc') },
                                        { value: 'syslog', label: t('ee.auditStream.kindSyslog'), description: t('ee.auditStream.kindSyslogDesc') },
                                    ]}
                                />
                            )}
                            {editing.kind === 'http' ? (
                                <>
                                    <Form.Group className="mb-3" controlId="stream-url">
                                        <Form.Label>{t('ee.auditStream.url')}</Form.Label>
                                        <Form.Control type="url" value={editing.url} placeholder="https://splunk.example.com:8088/services/collector/event"
                                            onChange={(e) => set({ url: e.target.value })} />
                                    </Form.Group>
                                    <ChoiceGroup
                                        label={t('ee.auditStream.format')}
                                        value={editing.http_format}
                                        onChange={(http_format) => set({ http_format })}
                                        options={[
                                            { value: 'json', label: t('ee.auditStream.formatJson') },
                                            { value: 'ndjson', label: t('ee.auditStream.formatNdjson') },
                                            { value: 'splunk_hec', label: t('ee.auditStream.formatSplunk') },
                                        ]}
                                    />
                                    <div className="row">
                                        <Form.Group className="mb-3 col-md-5" controlId="stream-header-name">
                                            <Form.Label>{t('ee.auditStream.headerName')}</Form.Label>
                                            <Form.Control value={editing.auth_header_name} placeholder={t('ee.auditStream.headerNamePlaceholder')}
                                                onChange={(e) => set({ auth_header_name: e.target.value })} />
                                        </Form.Group>
                                        <Form.Group className="mb-3 col-md-7" controlId="stream-header-value">
                                            <Form.Label>{t('ee.auditStream.headerValue')}</Form.Label>
                                            <Form.Control type="password" autoComplete="new-password" value={editing.auth_header_value}
                                                placeholder={original?.auth_header_configured ? t('ee.auditStream.configured') : ''}
                                                onChange={(e) => set({ auth_header_value: e.target.value, clear_auth: false })} />
                                            <Form.Text>{t('ee.auditStream.headerValueHint')}</Form.Text>
                                            {original?.auth_header_configured && (
                                                <Form.Check className="mt-1" id="stream-clear-auth" label={t('ee.auditStream.clear')}
                                                    checked={!!editing.clear_auth} onChange={(e) => set({ clear_auth: e.target.checked })} />
                                            )}
                                        </Form.Group>
                                    </div>
                                    <Form.Group className="mb-3" controlId="stream-signing-secret">
                                        <Form.Label>{t('ee.auditStream.signingSecret')}</Form.Label>
                                        <Form.Control type="password" autoComplete="new-password" value={editing.signing_secret}
                                            placeholder={original?.signing_secret_configured ? t('ee.auditStream.configured') : ''}
                                            onChange={(e) => set({ signing_secret: e.target.value, clear_signing: false })} />
                                        <Form.Text>{t('ee.auditStream.signingSecretHint')}</Form.Text>
                                        {original?.signing_secret_configured && (
                                            <Form.Check className="mt-1" id="stream-clear-signing" label={t('ee.auditStream.clear')}
                                                checked={!!editing.clear_signing} onChange={(e) => set({ clear_signing: e.target.checked })} />
                                        )}
                                    </Form.Group>
                                </>
                            ) : (
                                <>
                                    <ChoiceGroup
                                        label={t('ee.auditStream.transport')}
                                        value={editing.transport}
                                        onChange={(transport) => set({ transport, port: PORTS[transport] })}
                                        options={[
                                            { value: 'tls', label: t('ee.auditStream.transportTls') },
                                            { value: 'tcp', label: t('ee.auditStream.transportTcp') },
                                            { value: 'udp', label: t('ee.auditStream.transportUdp') },
                                        ]}
                                    />
                                    <div className="row">
                                        <Form.Group className="mb-3 col-md-8" controlId="stream-host">
                                            <Form.Label>{t('ee.auditStream.host')}</Form.Label>
                                            <Form.Control value={editing.host} placeholder="siem.example.com" onChange={(e) => set({ host: e.target.value })} />
                                        </Form.Group>
                                        <Form.Group className="mb-3 col-md-4" controlId="stream-port">
                                            <Form.Label>{t('ee.auditStream.port')}</Form.Label>
                                            <Form.Control type="number" min={1} max={65535} value={editing.port || ''}
                                                onChange={(e) => set({ port: e.target.value })} />
                                        </Form.Group>
                                    </div>
                                </>
                            )}
                            {(editing.kind === 'http' || editing.transport === 'tls') && (
                                <Form.Group className="mb-3" controlId="stream-ca">
                                    <Form.Label>{t('ee.auditStream.caCertificate')}</Form.Label>
                                    <Form.Control as="textarea" rows={4} value={editing.ca_certificate || ''} placeholder="-----BEGIN CERTIFICATE-----"
                                        onChange={(e) => set({ ca_certificate: e.target.value })} />
                                    <Form.Text>{t('ee.auditStream.caCertificateHint')}</Form.Text>
                                </Form.Group>
                            )}
                            <Form.Check type="switch" id="stream-enabled" label={t('ee.auditStream.enabled')}
                                checked={editing.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
                        </Modal.Body>
                        <Modal.Footer>
                            <Button variant="secondary" onClick={() => setEditing(null)}>{t('ee.auditStream.cancel')}</Button>
                            <Button variant="primary" onClick={save} disabled={saving || !editing.name.trim()}>{t('ee.auditStream.save')}</Button>
                        </Modal.Footer>
                    </>
                )}
            </Modal>
        </div>
    );
};

export default AuditStreamSettings;
