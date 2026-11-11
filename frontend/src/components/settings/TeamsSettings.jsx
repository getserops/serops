/**
 * Settings → Teams: groups of members that projects can be opened to
 * (Project → Access). Members added by an SSO group rule are marked; the
 * identity provider adds and removes those at each sign-in.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { Modal, Button, Form, Table, Spinner, Badge } from 'react-bootstrap';
import { FaPlus, FaEdit, FaTrash, FaUsers } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { OrganisationService } from '../../services/organisation.service';
import { usePermissions, getRoleDisplayName } from '../../utils/permissions';
import PageHeader from '../PageHeader';
import CollapsibleSection from './CollapsibleSection';
import './SettingsLayout.css';

const TeamsSettings = () => {
    const { t } = useTranslation();
    const can = usePermissions();
    const canManage = can('team.manage');
    const [teams, setTeams] = useState(null);
    const [people, setPeople] = useState([]);
    const [editing, setEditing] = useState(null);
    const [saving, setSaving] = useState(false);

    const load = useCallback(async () => {
        try {
            setTeams(await OrganisationService.getTeams());
        } catch {
            toast.error(t('teams.loadFailed'));
        }
    }, [t]);

    useEffect(() => {
        load();
        if (canManage) {
            OrganisationService.getTeamMembers(1, 500).then((r) => setPeople(r.users || [])).catch(() => setPeople([]));
        }
    }, [load, canManage]);

    const save = async () => {
        setSaving(true);
        const body = { name: editing.name, description: editing.description, member_ids: [...editing.memberIds] };
        try {
            if (editing.id) await OrganisationService.updateTeam(editing.id, body);
            else await OrganisationService.createTeam(body);
            toast.success(t('teams.saved'));
            setEditing(null);
            load();
        } catch (err) {
            const d = err?.response?.data || {};
            toast.error(d.error || d.name || d.member_ids || t('teams.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    const remove = async (team) => {
        if (!window.confirm(t('teams.confirmDelete', { name: team.name }))) return;
        try {
            await OrganisationService.deleteTeam(team.id);
            toast.success(t('teams.deleted'));
            load();
        } catch (err) {
            toast.error(err?.response?.data?.error || t('teams.deleteFailed'));
        }
    };

    const toggleMember = (id) => setEditing((e) => {
        const ids = new Set(e.memberIds);
        if (ids.has(id)) ids.delete(id); else ids.add(id);
        return { ...e, memberIds: ids };
    });

    if (!teams) {
        return <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>;
    }

    return (
        <div className="settings-section teams-settings">
            <PageHeader
                title={t('teams.title')}
                subtitle={t('teams.subtitle')}
                actions={canManage && (
                    <button className="btn btn-primary" onClick={() => setEditing({ id: null, name: '', description: '', memberIds: new Set() })}>
                        <FaPlus aria-hidden="true" />{t('teams.create')}
                    </button>
                )}
            />
            <CollapsibleSection className="ds-settings-section-flush" title={t('teams.list')} description={t('teams.listDesc')} defaultExpanded>
                {teams.length === 0 ? (
                    <div className="text-center py-5 text-muted">
                        <FaUsers size={40} className="mb-2 opacity-50" />
                        <p>{t('teams.none')}</p>
                        <p className="small">{t('teams.noneHint')}</p>
                    </div>
                ) : (
                <Table hover responsive className="table-stack settings-table teams-table mb-0">
                    <thead>
                        <tr>
                            <th>{t('teams.name')}</th>
                            <th>{t('teams.members')}</th>
                            <th>{t('teams.projects')}</th>
                            <th style={{ width: 100 }} />
                        </tr>
                    </thead>
                    <tbody>
                        {teams.map((team) => (
                            <tr key={team.id}>
                                <td data-label={t('teams.name')}>
                                    <div className="fw-medium">{team.name}</div>
                                    {team.description && <div className="text-muted small">{team.description}</div>}
                                </td>
                                <td data-label={t('teams.members')}>
                                    {team.members.length === 0 ? <span className="text-muted">—</span> : team.members.map((m) => (
                                        <div key={m.id} className="small">
                                            {m.name || m.email}
                                            {m.source === 'sso' && <Badge bg="secondary" className="ms-1">SSO</Badge>}
                                        </div>
                                    ))}
                                </td>
                                <td data-label={t('teams.projects')}>
                                    {team.projects.length === 0 ? <span className="text-muted">—</span> : team.projects.map((p) => (
                                        <div key={p.id} className="small">{p.name} · {getRoleDisplayName(p.role)}</div>
                                    ))}
                                </td>
                                <td className="text-end text-nowrap">
                                    {canManage && (
                                        <>
                                            <button type="button" className="btn btn-sm btn-outline-secondary me-1" aria-label={t('teams.edit', { name: team.name })} title={t('common.edit')}
                                                onClick={() => setEditing({ id: team.id, name: team.name, description: team.description, memberIds: new Set(team.members.map((m) => m.id)) })}>
                                                <FaEdit />
                                            </button>
                                            <button type="button" className="btn btn-sm btn-outline-danger" aria-label={t('teams.delete', { name: team.name })} title={t('common.delete')}
                                                onClick={() => remove(team)}>
                                                <FaTrash />
                                            </button>
                                        </>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </Table>
                )}
            </CollapsibleSection>

            <Modal show={!!editing} onHide={() => setEditing(null)} centered>
                {editing && (
                    <Form onSubmit={(e) => { e.preventDefault(); save(); }}>
                        <Modal.Header closeButton>
                            <Modal.Title>{editing.id ? t('teams.editTitle') : t('teams.createTitle')}</Modal.Title>
                        </Modal.Header>
                        <Modal.Body>
                            <Form.Group className="mb-3" controlId="team-name">
                                <Form.Label>{t('teams.name')}</Form.Label>
                                <Form.Control value={editing.name} maxLength={80} required placeholder={t('teams.namePlaceholder')}
                                    onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
                            </Form.Group>
                            <Form.Group className="mb-3" controlId="team-description">
                                <Form.Label>{t('teams.description')}</Form.Label>
                                <Form.Control value={editing.description} maxLength={255}
                                    onChange={(e) => setEditing({ ...editing, description: e.target.value })} />
                            </Form.Group>
                            <div className="form-label">{t('teams.members')}</div>
                            <div className="teams-member-picker">
                                {people.map((p) => (
                                    <Form.Check key={p.id} id={`member-${p.id}`} type="checkbox"
                                        checked={editing.memberIds.has(p.id)} onChange={() => toggleMember(p.id)}
                                        label={<span>{`${p.first_name || ''} ${p.last_name || ''}`.trim() || p.email} <span className="text-muted small">{p.email} · {p.role_name || getRoleDisplayName(p.role)}</span></span>} />
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

export default TeamsSettings;
