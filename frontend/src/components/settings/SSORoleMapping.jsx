/**
 * SSO group → role rules (Settings → Security → Single Sign-On).
 *
 * Rules are checked top to bottom; the first group the user is in sets
 * their role. With no match the default role applies, or the sign-in is
 * refused. The backend resolves it at each sign-in (Users/sso_roles.py).
 */
import React from 'react';
import { Table } from 'react-bootstrap';
import { FaArrowUp, FaArrowDown, FaTrash, FaPlus } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';

const SSORoleMapping = ({ sso, roles, teams = [], onChange }) => {
    const { t } = useTranslation();
    const rules = sso.role_mappings || [];
    const set = (patch) => onChange({ ...sso, ...patch });
    const setRules = (next) => set({ role_mappings: next });
    const update = (i, patch) => setRules(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
    const teamRules = sso.team_mappings || [];
    const setTeamRules = (next) => set({ team_mappings: next });
    const move = (i, d) => {
        const next = [...rules];
        [next[i], next[i + d]] = [next[i + d], next[i]];
        setRules(next);
    };

    return (
        <div className="settings-subsection sso-role-mapping">
            <h3 className="settings-subsection-title">{t('security.ssoRoles')}</h3>
            <p className="form-hint">{t('security.ssoRolesHint')}</p>

            <div className="row">
                <div className="col-md-6">
                    <div className="form-group mb-3">
                        <label htmlFor="sso-groups-claim">{t('security.groupsClaim')}</label>
                        <input
                            id="sso-groups-claim"
                            type="text"
                            className="form-control"
                            value={sso.groups_claim ?? 'groups'}
                            onChange={(e) => set({ groups_claim: e.target.value })}
                            placeholder="groups"
                        />
                        <small className="text-muted">{t('security.groupsClaimHint')}</small>
                    </div>
                </div>
                <div className="col-md-6">
                    <div className="form-group mb-3">
                        <label htmlFor="sso-extra-scopes">{t('security.extraScopes')}</label>
                        <input
                            id="sso-extra-scopes"
                            type="text"
                            className="form-control"
                            value={sso.extra_scopes || ''}
                            onChange={(e) => set({ extra_scopes: e.target.value })}
                            placeholder="groups"
                        />
                        <small className="text-muted">{t('security.extraScopesHint')}</small>
                    </div>
                </div>
            </div>

            {rules.length === 0 ? (
                <p className="form-hint">{t('security.noRules')}</p>
            ) : (
            <Table hover responsive className="table-stack settings-table sso-rules-table">
                <thead>
                    <tr>
                        <th>{t('security.ruleGroup')}</th>
                        <th>{t('security.ruleRole')}</th>
                        <th style={{ width: 130 }} />
                    </tr>
                </thead>
                <tbody>
                    {rules.map((rule, i) => (
                        <tr key={i}>
                            <td data-label={t('security.ruleGroup')}>
                                <input
                                    type="text"
                                    className="form-control"
                                    aria-label={t('security.ruleGroup')}
                                    value={rule.group}
                                    onChange={(e) => update(i, { group: e.target.value })}
                                    placeholder="platform-admins"
                                />
                            </td>
                            <td data-label={t('security.ruleRole')}>
                                <select
                                    className="form-select"
                                    aria-label={t('security.ruleRole')}
                                    value={rule.role}
                                    onChange={(e) => update(i, { role: e.target.value })}
                                >
                                    {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                                </select>
                            </td>
                            <td className="text-end text-nowrap">
                                <button type="button" className="btn btn-sm btn-outline-secondary me-1"
                                    aria-label={t('security.moveUp')} disabled={i === 0} onClick={() => move(i, -1)}>
                                    <FaArrowUp />
                                </button>
                                <button type="button" className="btn btn-sm btn-outline-secondary me-1"
                                    aria-label={t('security.moveDown')} disabled={i === rules.length - 1} onClick={() => move(i, 1)}>
                                    <FaArrowDown />
                                </button>
                                <button type="button" className="btn btn-sm btn-outline-danger"
                                    aria-label={t('security.removeRule')} onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                                    <FaTrash />
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </Table>
            )}
            <div className="mb-3">
                <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm"
                    onClick={() => setRules([...rules, { group: '', role: roles[0]?.value || 'viewer' }])}>
                    <FaPlus aria-hidden="true" />{t('security.addRule')}
                </button>
            </div>

            <div className="row">
                <div className="col-md-6">
                    <div className="form-group mb-3">
                        <label htmlFor="sso-default-role">{t('security.defaultRole')}</label>
                        <select
                            id="sso-default-role"
                            className="form-select"
                            value={sso.default_role || 'viewer'}
                            onChange={(e) => set({ default_role: e.target.value })}
                        >
                            {roles.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                            <option value="deny">{t('security.denySignIn')}</option>
                        </select>
                        <small className="text-muted">{t('security.defaultRoleHint')}</small>
                    </div>
                </div>
                <div className="col-md-6">
                    <div className="form-group mb-3">
                        <label htmlFor="sso-email-domains">{t('security.emailDomains')}</label>
                        <input
                            id="sso-email-domains"
                            type="text"
                            className="form-control"
                            value={sso.email_domains_text ?? (sso.email_domains || []).join(', ')}
                            onChange={(e) => set({ email_domains_text: e.target.value })}
                            disabled={!sso.email_domains_editable}
                            placeholder="example.com"
                        />
                        <small className="text-muted">
                            {sso.email_domains_editable ? t('security.emailDomainsHint') : t('security.emailDomainsStaffOnly')}
                        </small>
                    </div>
                </div>
            </div>

            <h3 className="settings-subsection-title mt-4">{t('security.ssoTeams')}</h3>
            <p className="form-hint">{t('security.ssoTeamsHint')}</p>
            {teamRules.length === 0 ? (
                <p className="form-hint">{(teams.length ? t('security.noTeamRules') : t('security.noTeamsYet'))}</p>
            ) : (
            <Table hover responsive className="table-stack settings-table sso-team-rules-table">
                <thead>
                    <tr>
                        <th>{t('security.ruleGroup')}</th>
                        <th>{t('security.ruleTeam')}</th>
                        <th style={{ width: 60 }} />
                    </tr>
                </thead>
                <tbody>
                    {teamRules.map((rule, i) => (
                        <tr key={i}>
                            <td data-label={t('security.ruleGroup')}>
                                <input type="text" className="form-control" aria-label={t('security.ruleGroup')} value={rule.group}
                                    onChange={(e) => setTeamRules(teamRules.map((r, j) => (j === i ? { ...r, group: e.target.value } : r)))}
                                    placeholder="payments-eng" />
                            </td>
                            <td data-label={t('security.ruleTeam')}>
                                <select className="form-select" aria-label={t('security.ruleTeam')} value={rule.team_id}
                                    onChange={(e) => setTeamRules(teamRules.map((r, j) => (j === i ? { ...r, team_id: Number(e.target.value) } : r)))}>
                                    {teams.map((tm) => <option key={tm.id} value={tm.id}>{tm.name}</option>)}
                                </select>
                            </td>
                            <td className="text-end">
                                <button type="button" className="btn btn-sm btn-outline-danger" aria-label={t('security.removeRule')}
                                    onClick={() => setTeamRules(teamRules.filter((_, j) => j !== i))}>
                                    <FaTrash />
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </Table>
            )}
            {teams.length > 0 && (
                <div className="mb-3">
                    <button type="button" className="ds-btn ds-btn-secondary ds-btn-sm"
                        onClick={() => setTeamRules([...teamRules, { group: '', team_id: teams[0].id }])}>
                        <FaPlus aria-hidden="true" />{t('security.addTeamRule')}
                    </button>
                </div>
            )}

            <label className="toggle-item large" htmlFor="sso-sync-role">
                <div className="toggle-label">
                    <span>{t('security.syncRole')}</span>
                    <small>{t('security.syncRoleHint')}</small>
                </div>
                <input
                    id="sso-sync-role"
                    type="checkbox"
                    checked={!!sso.sync_role}
                    onChange={(e) => set({ sync_role: e.target.checked })}
                />
                <span className="toggle-slider"></span>
            </label>
        </div>
    );
};

export default SSORoleMapping;
