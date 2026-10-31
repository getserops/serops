/**
 * DataCheckPanel — "Check my data" for a project.
 *
 * Shows what the last scheduled run of each environment did (and why it
 * made no analysis when it made none), and runs the check: the query the
 * scheduled analysis sends, one filter at a time, against the
 * organisation's own log store. Each step says how many logs are left,
 * the first empty step says what to change, and the values the logs
 * carry (project, environment, service) are listed so nobody has to
 * guess. Two fixes are one click: list a service seen in the logs, or
 * accept the environment value the logs carry.
 *
 * Used on the project page ("Data" tab) and in the onboarding wizard
 * while the first analysis is awaited.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { Alert, Badge, Button, Form, Spinner, Table } from 'react-bootstrap';
import { FaCheckCircle, FaTimesCircle, FaSearch } from 'react-icons/fa';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { ProjectService } from '../../services/project.service';
import { can } from '../../utils/permissions';
import { describeRequestError } from '../../utils/apiError';

const WINDOWS = [15, 60, 1440];

const OUTCOME_BADGE = { batch: 'success', empty: 'warning', skipped: 'secondary', error: 'danger' };

const DIAGNOSIS_VARIANT = { ok: 'success', no_errors: 'info' };

// Loki lists every stream: name a few, count the rest.
const shortList = (items, t, max = 4) => (items.length <= max
    ? items.join(', ')
    : `${items.slice(0, max).join(', ')} ${t('dataCheck.more', { count: items.length - max })}`);

const formatCount = (stage) => {
    if (stage.count === null || stage.count === undefined) return '—';
    return stage.capped ? `${stage.count}+` : String(stage.count);
};

function StepLabel({ stage, report, t }) {
    switch (stage.key) {
        case 'found':
            return t('dataCheck.step.found', { locations: shortList(report.locations, t) });
        case 'project':
            return t('dataCheck.step.project', { project: report.project });
        case 'environment':
            return t('dataCheck.step.environment', { values: report.environment_values.join(', ') });
        case 'level':
            return t('dataCheck.step.level');
        case 'services':
            return t('dataCheck.step.services');
        default:
            return stage.key;
    }
}

function SeenTable({ title, rows, showField, showRegistered, t }) {
    if (!rows || rows.length === 0) return null;
    return (
        <div className="settings-subsection">
            <h4 className="settings-subsection-title">{title}</h4>
            <Table hover responsive className="table-stack settings-table mb-0">
                <thead>
                    <tr>
                        <th>{t('dataCheck.value')}</th>
                        <th>{t('dataCheck.logs')}</th>
                        {showField && <th>{t('dataCheck.field')}</th>}
                        {showRegistered && <th>{t('dataCheck.listed')}</th>}
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row) => (
                        <tr key={row.value}>
                            <td data-label={t('dataCheck.value')}><code>{row.value}</code></td>
                            <td data-label={t('dataCheck.logs')}>{row.count}</td>
                            {showField && <td data-label={t('dataCheck.field')}><code>{row.field}</code></td>}
                            {showRegistered && (
                                <td data-label={t('dataCheck.listed')}>
                                    {row.registered ? t('common.yes', 'Yes') : t('common.no', 'No')}
                                </td>
                            )}
                        </tr>
                    ))}
                </tbody>
            </Table>
        </div>
    );
}

export default function DataCheckPanel({ projectId, environments = [], onFixed }) {
    const { t } = useTranslation();
    const activeEnvs = environments.filter((e) => e.is_active !== false);
    const [runs, setRuns] = useState([]);
    const [environment, setEnvironment] = useState('');
    const [minutes, setMinutes] = useState(60);
    const [checking, setChecking] = useState(false);
    const [report, setReport] = useState(null);
    const [error, setError] = useState(null);
    const [selected, setSelected] = useState([]);
    const [applying, setApplying] = useState(false);

    useEffect(() => {
        if (environment || !activeEnvs.length) return;
        // Production first: the environment people check first, and the one
        // their logs are most likely tagged with.
        const prod = activeEnvs.find((e) => ['production', 'prod', 'prd'].includes(String(e.name).toLowerCase()));
        setEnvironment(String((prod || activeEnvs[0]).id));
    }, [activeEnvs, environment]);

    const loadRuns = useCallback(async () => {
        try {
            const data = await ProjectService.GetDataRuns(projectId);
            setRuns(Array.isArray(data?.runs) ? data.runs : []);
        } catch {
            setRuns([]);
        }
    }, [projectId]);

    useEffect(() => { loadRuns(); }, [loadRuns]);

    const runCheck = async () => {
        setChecking(true);
        setError(null);
        try {
            const data = await ProjectService.CheckData(projectId, {
                environment: environment || undefined,
                minutes,
            });
            setReport(data);
            const offered = (data.fixes || []).find((f) => f.action === 'register_services');
            setSelected(offered ? offered.names : []);
        } catch (err) {
            setError(describeRequestError(err, t('dataCheck.failed')));
        } finally {
            setChecking(false);
        }
    };

    const applyFix = async (fix, done) => {
        setApplying(true);
        try {
            await ProjectService.ApplyDataFix(projectId, fix);
            toast.success(done);
            onFixed?.();
            await runCheck();
        } catch (err) {
            toast.error(describeRequestError(err, t('dataCheck.fixFailed')));
        } finally {
            setApplying(false);
        }
    };

    const envName = (id) => {
        const env = environments.find((e) => e.id === id);
        return env ? (env.display_name || env.name) : t('dataCheck.wholeProject');
    };

    const serviceFix = report?.fixes?.find((f) => f.action === 'register_services');
    const envFixes = (report?.fixes || []).filter((f) => f.action === 'use_environment_label');
    const firstEmpty = report?.stages?.findIndex((s) => !s.count);

    return (
        <section className="ds-settings-section" aria-labelledby="data-check-title">
            <div className="ds-settings-section-head">
                <div className="ds-settings-section-text">
                    <h3 id="data-check-title" className="ds-settings-section-title">{t('dataCheck.title')}</h3>
                    <p className="ds-settings-section-desc">{t('dataCheck.description')}</p>
                </div>
            </div>
            <div className="ds-settings-section-body">
                {runs.length > 0 && (
                    <div className="settings-subsection border-0 pt-0">
                        <h4 className="settings-subsection-title">{t('dataCheck.lastRuns')}</h4>
                        <Table hover responsive className="table-stack settings-table mb-0">
                            <thead>
                                <tr>
                                    <th>{t('dataCheck.environment')}</th>
                                    <th>{t('dataCheck.result')}</th>
                                    <th>{t('dataCheck.why')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {runs.map((run) => (
                                    <tr key={`${run.environment}-${run.ran_at}`}>
                                        <td data-label={t('dataCheck.environment')}>
                                            {/* one child: stacked rows lay a cell's children side by side */}
                                            <div>
                                                <div>{envName(run.environment)}</div>
                                                <div className="form-hint">{new Date(run.ran_at).toLocaleString()}</div>
                                            </div>
                                        </td>
                                        <td data-label={t('dataCheck.result')}>
                                            <Badge bg={OUTCOME_BADGE[run.outcome] || 'secondary'}>
                                                {t(`dataCheck.outcome.${run.outcome}`)}
                                            </Badge>
                                        </td>
                                        <td data-label={t('dataCheck.why')}>
                                            {run.reason
                                                ? t(`dataCheck.reason.${run.reason}`, { defaultValue: run.detail || '—' })
                                                : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    </div>
                )}

                {can('integration.use') ? (
                    <div className="settings-inline-form">
                        {activeEnvs.length > 0 && (
                            <Form.Group controlId="data-check-environment">
                                <Form.Label>{t('dataCheck.environment')}</Form.Label>
                                <Form.Select className="settings-select" value={environment}
                                    onChange={(e) => setEnvironment(e.target.value)}>
                                    {activeEnvs.map((env) => (
                                        <option key={env.id} value={env.id}>{env.display_name || env.name}</option>
                                    ))}
                                </Form.Select>
                            </Form.Group>
                        )}
                        <Form.Group controlId="data-check-window">
                            <Form.Label>{t('dataCheck.window')}</Form.Label>
                            <Form.Select className="settings-select" value={minutes}
                                onChange={(e) => setMinutes(Number(e.target.value))}>
                                {WINDOWS.map((m) => (
                                    <option key={m} value={m}>{t(`dataCheck.windows.${m}`)}</option>
                                ))}
                            </Form.Select>
                        </Form.Group>
                        <Button variant="primary" onClick={runCheck} disabled={checking}>
                            {checking
                                ? <Spinner animation="border" size="sm" role="status" aria-hidden="true" />
                                : <FaSearch size={13} aria-hidden="true" />}
                            <span>{checking ? t('dataCheck.checking') : t('dataCheck.run')}</span>
                        </Button>
                    </div>
                ) : (
                    <p className="form-hint mb-0">{t('dataCheck.noPermission')}</p>
                )}

                {error && <Alert variant="danger" className="mb-0">{error}</Alert>}

                {report && (
                    <>
                        <Alert variant={DIAGNOSIS_VARIANT[report.diagnosis?.code] || 'warning'}
                            className="mb-0" role="status">
                            {report.diagnosis && t(`dataCheck.diagnosis.${report.diagnosis.code}`, {
                                ...report.diagnosis,
                                defaultValue: report.diagnosis.message,
                            })}
                            {(report.diagnosis?.same_but_case || []).map((value) => (
                                <div key={value} className="mt-2">{t('dataCheck.caseHint', { value })}</div>
                            ))}
                        </Alert>

                        {report.stages.length > 0 && (
                            <div className="settings-subsection">
                                <h4 className="settings-subsection-title">
                                    {t('dataCheck.steps', { minutes: report.window_minutes })}
                                </h4>
                                <Table hover responsive className="table-stack settings-table mb-0">
                                    <thead>
                                        <tr>
                                            <th>{t('dataCheck.step.title')}</th>
                                            <th>{t('dataCheck.logs')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {report.stages.map((stage, i) => (
                                            <tr key={stage.key}>
                                                <td data-label={t('dataCheck.step.title')}>
                                                    <div>
                                                    <span className="d-inline-flex align-items-center gap-2">
                                                        {stage.count
                                                            ? <FaCheckCircle className="text-success flex-shrink-0" aria-hidden="true" />
                                                            : <FaTimesCircle className={`flex-shrink-0 ${i === firstEmpty ? 'text-danger' : 'text-muted'}`} aria-hidden="true" />}
                                                        <StepLabel stage={stage} report={report} t={t} />
                                                    </span>
                                                    {stage.error && <div className="form-hint">{stage.error}</div>}
                                                    </div>
                                                </td>
                                                <td data-label={t('dataCheck.logs')}>{formatCount(stage)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </Table>
                            </div>
                        )}

                        {can('project.write') && envFixes.length > 0 && (
                            <div className="settings-subsection">
                                <h4 className="settings-subsection-title">{t('dataCheck.fixEnvironment')}</h4>
                                <div className="d-flex flex-wrap gap-2">
                                    {envFixes.map((fix) => (
                                        <Button key={fix.value} variant="outline-secondary" size="sm" disabled={applying}
                                            onClick={() => applyFix(fix, t('dataCheck.envFixed', { value: fix.value }))}>
                                            {t('dataCheck.useValue', { value: fix.value, environment: report.environment })}
                                        </Button>
                                    ))}
                                </div>
                                <p className="form-hint mb-0">{t('dataCheck.useValueHint')}</p>
                            </div>
                        )}

                        {report.project_rules?.length > 0 && (
                            <div className="settings-subsection">
                                <h4 className="settings-subsection-title">{t('dataCheck.rules.title')}</h4>
                                <p className="form-hint mb-0">{t('dataCheck.rules.hint', { project: report.project })}</p>
                                <Table hover responsive className="table-stack settings-table mb-0">
                                    <thead>
                                        <tr>
                                            <th>{t('dataCheck.field')}</th>
                                            <th>{t('dataCheck.value')}</th>
                                            {can('project.write') && <th aria-label={t('data.actions')} />}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {report.project_rules.map((rule) => (
                                            <tr key={`${rule.field}=${rule.value}`}>
                                                <td data-label={t('dataCheck.field')}><code>{rule.field}</code></td>
                                                <td data-label={t('dataCheck.value')}><code>{rule.value}</code></td>
                                                {can('project.write') && (
                                                    <td className="text-end">
                                                        <Button variant="outline-danger" size="sm" disabled={applying}
                                                            onClick={() => applyFix({ action: 'remove_project_rule', ...rule },
                                                                t('dataCheck.rules.removed'))}>
                                                            {t('common.remove', 'Remove')}
                                                        </Button>
                                                    </td>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </Table>
                            </div>
                        )}

                        {report.seen.groupings?.length > 0 && (
                            <div className="settings-subsection">
                                <h4 className="settings-subsection-title">{t('dataCheck.groupings.title')}</h4>
                                <p className="form-hint mb-0">{t('dataCheck.groupings.hint', { project: report.project })}</p>
                                <Table hover responsive className="table-stack settings-table mb-0">
                                    <thead>
                                        <tr>
                                            <th>{t('dataCheck.field')}</th>
                                            <th>{t('dataCheck.value')}</th>
                                            <th>{t('dataCheck.logs')}</th>
                                            {can('project.write') && <th aria-label={t('data.actions')} />}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {report.seen.groupings.map((g) => (
                                            <tr key={`${g.field}=${g.value}`}>
                                                <td data-label={t('dataCheck.field')}><code>{g.field}</code></td>
                                                <td data-label={t('dataCheck.value')}>
                                                    <code>{g.value}</code>
                                                    {g.matches_name && <Badge bg="success" className="ms-2">{t('dataCheck.groupings.sameName')}</Badge>}
                                                </td>
                                                <td data-label={t('dataCheck.logs')}>{g.count}</td>
                                                {can('project.write') && (
                                                    <td className="text-end">
                                                        <Button variant={g.matches_name ? 'primary' : 'outline-secondary'} size="sm"
                                                            disabled={applying || (report.project_rules?.length || 0) >= 5}
                                                            onClick={() => applyFix({ action: 'add_project_rule', field: g.field, value: g.value },
                                                                t('dataCheck.groupings.added', { field: g.field, value: g.value }))}>
                                                            {t('dataCheck.groupings.use')}
                                                        </Button>
                                                    </td>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </Table>
                            </div>
                        )}

                        {can('project.write') && serviceFix && (
                            <div className="settings-subsection">
                                <h4 className="settings-subsection-title">{t('dataCheck.fixServices')}</h4>
                                {serviceFix.names.map((name) => (
                                    <Form.Check key={name} id={`data-check-service-${name}`} type="checkbox"
                                        label={<code>{name}</code>}
                                        checked={selected.includes(name)}
                                        onChange={(e) => setSelected(e.target.checked
                                            ? [...selected, name]
                                            : selected.filter((n) => n !== name))} />
                                ))}
                                <div>
                                    <Button variant="primary" size="sm" disabled={applying || selected.length === 0}
                                        onClick={() => applyFix({ action: 'register_services', names: selected },
                                            t('dataCheck.servicesAdded', { count: selected.length }))}>
                                        {t('dataCheck.addServices', { count: selected.length })}
                                    </Button>
                                </div>
                            </div>
                        )}

                        <SeenTable title={t('dataCheck.seen.project')} rows={report.seen.project} showField t={t} />
                        <SeenTable title={t('dataCheck.seen.environment')} rows={report.seen.environment} showField t={t} />
                        <SeenTable title={t('dataCheck.seen.service')} rows={report.seen.service} showRegistered t={t} />
                        <p className="form-hint mb-0">{t('dataCheck.privacy', { size: report.sample_size })}</p>
                    </>
                )}
            </div>
        </section>
    );
}
