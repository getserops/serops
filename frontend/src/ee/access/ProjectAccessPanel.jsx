/**
 * Project → Access (Enterprise, feature project_access): who sees this
 * project.
 *
 * Everyone in the organisation (their roles apply), or only the teams
 * given access, each with a role on this project. Organisation admins
 * always see every project. Grants add to what members' organisation
 * roles allow. Backend: ee/access/projects.py. Without a license the
 * restrictions keep applying and can only be lowered, removed or opened.
 */
import React, { useEffect, useState } from 'react';
import { Table, Spinner } from 'react-bootstrap';
import { FaTrash } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { OrganisationService } from '../../services/organisation.service';
import { getRoleDisplayName } from '../../utils/permissions';
import { hasFeature, useEdition } from '../../utils/edition';
import ChoiceGroup from '../../components/settings/ChoiceGroup';
import { AccessService } from './service';
import '../../components/settings/SettingsLayout.css';

const PROJECT_ROLES = ['viewer', 'user', 'admin'];

const ProjectAccessPanel = ({ projectId }) => {
    const { t } = useTranslation();
    const licensed = hasFeature(useEdition(), 'project_access');
    const [access, setAccess] = useState(null);
    const [saved, setSaved] = useState(null);
    const [teams, setTeams] = useState([]);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let cancelled = false;
        Promise.all([AccessService.getProjectAccess(projectId), OrganisationService.getTeams()])
            .then(([a, ts]) => { if (!cancelled) { setAccess(a); setSaved(a); setTeams(ts); } })
            .catch(() => toast.error(t('projectAccess.loadFailed')));
        return () => { cancelled = true; };
    }, [projectId, t]);

    if (!access) {
        return <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>;
    }

    const grants = access.grants || [];
    const setGrants = (next) => setAccess({ ...access, grants: next });
    const available = teams.filter((tm) => !grants.some((g) => g.team_id === tm.id));
    // Without a license: nothing may become more restricted or more granted.
    const savedRole = (teamId) => (saved?.grants || []).find((g) => g.team_id === teamId)?.role;
    const roleChoices = (teamId) => (licensed ? PROJECT_ROLES
        : PROJECT_ROLES.slice(0, PROJECT_ROLES.indexOf(savedRole(teamId)) + 1));

    const save = async () => {
        setSaving(true);
        try {
            const result = await AccessService.updateProjectAccess(projectId, {
                access_mode: access.access_mode,
                grants: grants.map((g) => ({ team_id: g.team_id, role: g.role })),
            });
            setAccess(result);
            setSaved(result);
            toast.success(t('projectAccess.saved'));
        } catch (err) {
            toast.error(err?.response?.data?.error || t('projectAccess.saveFailed'));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="project-access-panel p-4">
            {!licensed && <div className="alert alert-info small" role="note">{t('ee.access.accessUnlicensed')}</div>}
            <ChoiceGroup
                variant="cards"
                label={t('projectAccess.whoSees')}
                value={access.access_mode}
                onChange={(mode) => setAccess({ ...access, access_mode: mode })}
                hint={access.access_mode === 'restricted' ? t('projectAccess.restrictedHint') : t('projectAccess.organisationHint')}
                options={[
                    { value: 'organisation', label: t('projectAccess.organisation') },
                    { value: 'restricted', label: t('projectAccess.restricted'),
                      disabled: !licensed && saved?.access_mode !== 'restricted' },
                ]}
            />

            <h3 className="settings-subsection-title mt-4">{t('projectAccess.teams')}</h3>
            <p className="form-hint">{t('projectAccess.teamsHint')}</p>
            {grants.length === 0 ? (
                <p className="form-hint">{t('projectAccess.noTeams')}</p>
            ) : (
            <Table hover responsive className="table-stack settings-table project-access-table">
                <thead>
                    <tr>
                        <th>{t('projectAccess.team')}</th>
                        <th>{t('projectAccess.role')}</th>
                        <th style={{ width: 60 }} />
                    </tr>
                </thead>
                <tbody>
                    {grants.map((g, i) => (
                        <tr key={g.team_id}>
                            <td className="fw-medium" data-label={t('projectAccess.team')}>{g.team_name || teams.find((tm) => tm.id === g.team_id)?.name}</td>
                            <td data-label={t('projectAccess.role')}>
                                <select className="form-select" aria-label={t('projectAccess.role')} value={g.role}
                                    onChange={(e) => setGrants(grants.map((x, j) => (j === i ? { ...x, role: e.target.value } : x)))}>
                                    {roleChoices(g.team_id).map((r) => <option key={r} value={r}>{getRoleDisplayName(r)}</option>)}
                                </select>
                            </td>
                            <td className="text-end">
                                <button type="button" className="btn btn-sm btn-outline-danger"
                                    aria-label={t('projectAccess.remove', { team: g.team_name })} title={t('common.delete')}
                                    onClick={() => setGrants(grants.filter((_, j) => j !== i))}>
                                    <FaTrash />
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </Table>
            )}
            {licensed && available.length > 0 && (
                <div className="mb-3">
                    <select className="form-select settings-select" aria-label={t('projectAccess.addTeam')} defaultValue=""
                        onChange={(e) => {
                            const team = teams.find((tm) => String(tm.id) === e.target.value);
                            if (team) setGrants([...grants, { team_id: team.id, team_name: team.name, role: 'viewer' }]);
                            e.target.value = '';
                        }}>
                        <option value="" disabled>{t('projectAccess.addTeam')}</option>
                        {available.map((tm) => <option key={tm.id} value={tm.id}>{tm.name}</option>)}
                    </select>
                </div>
            )}
            {licensed && teams.length === 0 && <p className="form-hint">{t('projectAccess.createTeamsFirst')}</p>}

            <div className="settings-page-actions">
                <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
                    {saving ? t('common.saving') : t('common.saveChanges')}
                </button>
            </div>
        </div>
    );
};

export default ProjectAccessPanel;
