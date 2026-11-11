/**
 * Settings → Roles (Enterprise, feature custom_roles): the built-in roles,
 * and custom roles built from the permission catalogue. Listing is the
 * Community API (Organisations/role_views.py); writes go to ee/access.
 *
 * The permissions every role holds are always on; picking a permission
 * also picks the one it needs (write needs read). The API refuses a role
 * with permissions the editor doesn't hold, and deleting a role in use.
 * Without a license, existing roles are shown and can be deleted, not
 * created or edited.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Modal, Button, Form, Table, Spinner } from 'react-bootstrap';
import { FaPlus, FaEdit, FaTrash, FaIdBadge } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { OrganisationService } from '../../services/organisation.service';
import { usePermissions } from '../../utils/permissions';
import { hasFeature, useEdition } from '../../utils/edition';
import PageHeader from '../../components/PageHeader';
import CollapsibleSection from '../../components/settings/CollapsibleSection';
import { AccessService } from './service';
import '../../components/settings/SettingsLayout.css';

const EMPTY = { id: null, name: '', description: '', permissions: [] };

const RolesSettings = () => {
    const { t } = useTranslation();
    const can = usePermissions();
    const canManage = can('team.manage');
    const licensed = hasFeature(useEdition(), 'custom_roles');
    const [data, setData] = useState(null);
    const [editing, setEditing] = useState(null);
    const [saving, setSaving] = useState(false);
    const [expanded, setExpanded] = useState(null);

    const load = useCallback(async () => {
        try {
            setData(await OrganisationService.getRoles());
        } catch {
            toast.error(t('roles.loadFailed'));
        }
    }, [t]);
    useEffect(() => { load(); }, [load]);

    const label = (code) => t(`roles.perm.${code}`, { defaultValue: data?.catalogue.find((c) => c.code === code)?.description || code });
    const groups = useMemo(() => {
        const out = {};
        (data?.catalogue || []).forEach((c) => {
            const g = c.code.split('.')[0];
            (out[g] = out[g] || []).push(c.code);
        });
        return out;
    }, [data]);

    // What the role will hold: the picks, what every role holds, and what
    // the picks need.
    const effective = (picked) => {
        const set = new Set([...picked, ...(data?.always_granted || [])]);
        picked.forEach((c) => data?.implies?.[c] && set.add(data.implies[c]));
        return set;
    };
    const lockedReason = (code, picked) => {
        if ((data?.always_granted || []).includes(code)) return t('roles.alwaysGranted');
        const needer = picked.find((c) => data?.implies?.[c] === code);
        return needer ? t('roles.neededBy', { permission: label(needer) }) : null;
    };

    const toggle = (code) => setEditing((e) => {
        const picked = e.permissions.includes(code) ? e.permissions.filter((c) => c !== code) : [...e.permissions, code];
        return { ...e, permissions: picked };
    });

    const save = async () => {
        setSaving(true);
        const body = { name: editing.name, description: editing.description, permissions: editing.permissions };
        try {
            if (editing.id) await AccessService.updateRole(editing.id, body);
            else await AccessService.createRole(body);
            toast.success(t('roles.saved'));
            setEditing(null);
            load();
        } catch (err) {
            const d = err?.response?.data || {};
            toast.error(d.error || d.name || d.permissions || t('roles.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const remove = async (role) => {
        if (!window.confirm(t('roles.confirmDelete', { name: role.name }))) return;
        try {
            await AccessService.deleteRole(role.id);
            toast.success(t('roles.deleted'));
            load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('roles.deleteFailed'));
        }
    };

    if (!data) {
        return <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>;
    }

    const permissionList = (codes) => (
        <ul className="roles-permission-list">
            {codes.map((c) => <li key={c}><code>{c}</code> {label(c)}</li>)}
        </ul>
    );

    return (
        <div className="settings-section roles-settings">
            <PageHeader
                title={t('roles.title')}
                subtitle={t('roles.subtitle')}
                actions={canManage && licensed && (
                    <button className="btn btn-primary" onClick={() => setEditing({ ...EMPTY })}>
                        <FaPlus aria-hidden="true" />{t('roles.create')}
                    </button>
                )}
            />

            {!licensed && (
                <div className="alert alert-info small" role="note">
                    {t('ee.access.rolesUnlicensed')}{' '}
                    {can('license.manage') && <Link to="/dash/settings/license">{t('ee.access.licenseLink')}</Link>}
                </div>
            )}

            <CollapsibleSection className="ds-settings-section-flush" title={t('roles.custom')} description={t('roles.customDesc')} defaultExpanded>
                {data.custom.length === 0 ? (
                    <div className="text-center py-5 text-muted">
                        <FaIdBadge size={40} className="mb-2 opacity-50" />
                        <p>{t('roles.none')}</p>
                        <p className="small">{t('roles.noneHint')}</p>
                    </div>
                ) : (
                <Table hover responsive className="table-stack settings-table roles-table mb-0">
                    <thead>
                        <tr>
                            <th>{t('roles.name')}</th>
                            <th>{t('roles.permissions')}</th>
                            <th>{t('roles.members')}</th>
                            <th style={{ width: 100 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {data.custom.map((role) => (
                            <React.Fragment key={role.id}>
                                <tr>
                                    <td data-label={t('roles.name')}>
                                        <div className="fw-medium">{role.name}</div>
                                        {role.description && <div className="text-muted small">{role.description}</div>}
                                    </td>
                                    <td data-label={t('roles.permissions')}>
                                        <button type="button" className="btn btn-link p-0" onClick={() => setExpanded(expanded === role.key ? null : role.key)}>
                                            {t('roles.permissionCount', { count: role.permissions.length })}
                                        </button>
                                    </td>
                                    <td data-label={t('roles.members')}>{role.member_count}</td>
                                    <td className="text-end text-nowrap">
                                        {canManage && (
                                            <>
                                                {licensed && (
                                                <button type="button" className="btn btn-sm btn-outline-secondary me-1" aria-label={t('roles.edit', { name: role.name })} title={t('common.edit')}
                                                    onClick={() => setEditing({ id: role.id, name: role.name, description: role.description, permissions: role.permissions })}>
                                                    <FaEdit />
                                                </button>
                                                )}
                                                <button type="button" className="btn btn-sm btn-outline-danger" aria-label={t('roles.delete', { name: role.name })} title={t('common.delete')}
                                                    onClick={() => remove(role)}>
                                                    <FaTrash />
                                                </button>
                                            </>
                                        )}
                                    </td>
                                </tr>
                                {expanded === role.key && (
                                    <tr><td colSpan={4}>{permissionList(role.permissions)}</td></tr>
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </Table>
                )}
            </CollapsibleSection>

            <CollapsibleSection className="ds-settings-section-flush" title={t('roles.builtin')} description={t('roles.builtinDesc')} defaultExpanded>
                <Table hover responsive className="table-stack settings-table roles-table mb-0">
                    <thead>
                        <tr><th>{t('roles.name')}</th><th>{t('roles.permissions')}</th></tr>
                    </thead>
                    <tbody>
                        {data.builtin.map((role) => (
                            <React.Fragment key={role.key}>
                                <tr>
                                    <td className="fw-medium" data-label={t('roles.name')}>{role.name}</td>
                                    <td data-label={t('roles.permissions')}>
                                        <button type="button" className="btn btn-link p-0" onClick={() => setExpanded(expanded === role.key ? null : role.key)}>
                                            {t('roles.permissionCount', { count: role.permissions.length })}
                                        </button>
                                    </td>
                                </tr>
                                {expanded === role.key && (
                                    <tr><td colSpan={2}>{permissionList(role.permissions)}</td></tr>
                                )}
                            </React.Fragment>
                        ))}
                    </tbody>
                </Table>
            </CollapsibleSection>

            <Modal show={!!editing} onHide={() => setEditing(null)} size="lg" centered>
                {editing && (
                    <Form onSubmit={(e) => { e.preventDefault(); save(); }}>
                        <Modal.Header closeButton>
                            <Modal.Title>{editing.id ? t('roles.editTitle') : t('roles.createTitle')}</Modal.Title>
                        </Modal.Header>
                        <Modal.Body>
                            <Form.Group className="mb-3" controlId="role-name">
                                <Form.Label>{t('roles.name')}</Form.Label>
                                <Form.Control value={editing.name} maxLength={50} required
                                    onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder={t('roles.namePlaceholder')} />
                            </Form.Group>
                            <Form.Group className="mb-3" controlId="role-description">
                                <Form.Label>{t('roles.description')}</Form.Label>
                                <Form.Control value={editing.description} maxLength={255}
                                    onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
                            </Form.Group>
                            <div className="form-label">{t('roles.permissions')}</div>
                            <p className="form-hint">{t('roles.permissionsHint')}</p>
                            <div className="roles-permission-groups">
                                {Object.entries(groups).map(([group, codes]) => (
                                    <fieldset key={group} className="roles-permission-group">
                                        <legend>{t(`roles.group.${group}`, { defaultValue: group })}</legend>
                                        {codes.map((code) => {
                                            const held = effective(editing.permissions);
                                            const reason = lockedReason(code, editing.permissions);
                                            return (
                                                <Form.Check
                                                    key={code}
                                                    id={`perm-${code}`}
                                                    type="checkbox"
                                                    checked={held.has(code)}
                                                    disabled={!!reason}
                                                    onChange={() => toggle(code)}
                                                    label={<span>{label(code)}{reason && <span className="text-muted small"> · {reason}</span>}</span>}
                                                />
                                            );
                                        })}
                                    </fieldset>
                                ))}
                            </div>
                        </Modal.Body>
                        <Modal.Footer>
                            <Button variant="light" onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
                            <Button variant="primary" type="submit" disabled={saving || !editing.name.trim()}>
                                {saving ? t('common.saving') : t('common.save')}
                            </Button>
                        </Modal.Footer>
                    </Form>
                )}
            </Modal>
        </div>
    );
};

export default RolesSettings;
