import React, { useState, useEffect } from 'react';
import {
    FaHistory, FaSearch, FaDownload, FaFilter, FaUser,
    FaCalendar, FaSpinner, FaChevronLeft, FaChevronRight,
    FaSignInAlt, FaSignOutAlt, FaCog, FaServer, FaTrash,
    FaUserPlus, FaRobot, FaBell, FaKey, FaTimes,
    FaChevronDown, FaChevronUp
} from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import enterpriseSettingsService from '../../services/enterpriseSettings.service';
import { OrganisationService } from '../../services/organisation.service';
import './SettingsLayout.css';

const ACTION_ICONS = {
    'LOGIN': FaSignInAlt,
    'LOGIN_FAILED': FaTimes,
    'LOGOUT': FaSignOutAlt,
    'PASSWORD_CHANGE': FaKey,
    'SETTINGS_CHANGE': FaCog,
    'SERVICE_CREATE': FaServer,
    'SERVICE_UPDATE': FaServer,
    'SERVICE_DELETE': FaTrash,
    'BATCH_DELETE': FaTrash,
    'BATCH_CLEANUP': FaTrash,
    'TEAM_INVITE': FaUserPlus,
    'TEAM_REMOVE': FaUser,
    'TEAM_ROLE_CHANGE': FaUser,
    'AI_MODEL_CHANGE': FaRobot,
    'NOTIFICATION_TEST': FaBell,
    'EXPORT_DATA': FaDownload,
};

const EMPTY_FILTERS = {
    action: '',
    user_id: '',
    search: '',
    date_from: '',
    date_to: '',
    page: 1
};

const AuditLogSettings = () => {
    const { t } = useTranslation();
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [exporting, setExporting] = useState(false);
    const [error, setError] = useState(null);
    const [pagination, setPagination] = useState(null);
    const [actionTypes, setActionTypes] = useState({});
    const [teamMembers, setTeamMembers] = useState([]);
    const [expandedRows, setExpandedRows] = useState(() => new Set());

    // Filters
    const [filters, setFilters] = useState(EMPTY_FILTERS);

    useEffect(() => {
        loadLogs();
    }, [filters.action, filters.user_id, filters.page]);

    useEffect(() => {
        // Team member list feeds the "filter by user" dropdown. Failing
        // here must not block the primary audit list — degrade silently.
        OrganisationService
            .getTeamMembers(1, 200)
            .then((data) => {
                const members = data?.results || data?.members || data || [];
                setTeamMembers(Array.isArray(members) ? members : []);
            })
            .catch(() => setTeamMembers([]));
    }, []);

    const loadLogs = async () => {
        try {
            setLoading(true);
            const params = { page: filters.page };
            if (filters.action) params.action = filters.action;
            if (filters.user_id) params.user_id = filters.user_id;
            if (filters.search) params.search = filters.search;
            if (filters.date_from) params.date_from = filters.date_from;
            if (filters.date_to) params.date_to = filters.date_to;

            const data = await enterpriseSettingsService.getAuditLogs(params);
            if (data) {
                setLogs(data.logs || []);
                setPagination(data.pagination || null);
                setActionTypes(data.action_types || {});
            } else {
                setLogs([]);
                setActionTypes({});
            }
        } catch (err) {
            setError(t('auditLog.loadFailed'));
        } finally {
            setLoading(false);
        }
    };

    const handleSearch = (e) => {
        e.preventDefault();
        setFilters({ ...filters, page: 1 });
        loadLogs();
    };

    const handleExport = async () => {
        try {
            setExporting(true);
            const params = {};
            if (filters.action) params.action = filters.action;
            if (filters.user_id) params.user_id = filters.user_id;
            if (filters.date_from) params.date_from = filters.date_from;
            if (filters.date_to) params.date_to = filters.date_to;

            await enterpriseSettingsService.exportAuditLogs(params);
        } catch (err) {
            setError(t('auditLog.exportFailed'));
        } finally {
            setExporting(false);
        }
    };

    const handleClearFilters = () => {
        setFilters(EMPTY_FILTERS);
    };

    const toggleRow = (id) => {
        setExpandedRows((prev) => {
            const next = new Set(prev);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    };

    const hasDetails = (details) =>
        details && typeof details === 'object' && Object.keys(details).length > 0;

    const formatDate = (isoDate) => {
        const date = new Date(isoDate);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    };

    const summarizeDetails = (details) => {
        // Short one-line summary shown when the row is collapsed.
        // Nested values are stringified so the summary stays readable
        // instead of showing "[object Object]".
        if (!hasDetails(details)) return '-';

        return Object.entries(details)
            .map(([key, value]) => {
                const rendered =
                    typeof value === 'object' && value !== null
                        ? JSON.stringify(value)
                        : String(value);
                return `${key}: ${rendered}`;
            })
            .join(', ');
    };

    const getActionColor = (action) => {
        if (action.includes('DELETE') || action.includes('REMOVE') || action === 'LOGIN_FAILED') {
            return 'danger';
        }
        if (action.includes('CREATE') || action === 'LOGIN' || action.includes('INVITE')) {
            return 'success';
        }
        if (action.includes('CHANGE') || action.includes('UPDATE')) {
            return 'warning';
        }
        return 'info';
    };

    return (
        <div className="settings-section">
            <div className="settings-header">
                <div className="settings-icon-wrapper audit">
                    <FaHistory />
                </div>
                <div>
                    <h2>{t('auditLog.title')}</h2>
                    <p>{t('auditLog.subtitle')}</p>
                </div>
            </div>

            {error && <div className="alert alert-danger">{error}</div>}

            {/* Filters Card */}
            <div className="settings-card mb-4">
                <div className="settings-card-body p-4">
                    <form onSubmit={handleSearch} className="row g-3 align-items-end">
                        <div className="col-md-2">
                            <label className="settings-form-label">{t('auditLog.actionType')}</label>
                            <div className="input-group">
                                <span className="input-group-text bg-white border-end-0"><FaFilter className="text-muted" /></span>
                                <select
                                    className="form-select border-start-0 ps-0"
                                    value={filters.action}
                                    onChange={(e) => setFilters({ ...filters, action: e.target.value, page: 1 })}
                                >
                                    <option value="">{t('auditLog.allActions')}</option>
                                    {Object.entries(actionTypes || {}).map(([value, label]) => (
                                        <option key={value} value={value}>{label}</option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="col-md-2">
                            <label className="settings-form-label">{t('auditLog.userFilter')}</label>
                            <div className="input-group">
                                <span className="input-group-text bg-white border-end-0"><FaUser className="text-muted" /></span>
                                <select
                                    className="form-select border-start-0 ps-0"
                                    value={filters.user_id}
                                    onChange={(e) => setFilters({ ...filters, user_id: e.target.value, page: 1 })}
                                >
                                    <option value="">{t('auditLog.allUsers')}</option>
                                    {teamMembers.map((member) => (
                                        <option key={member.id} value={member.id}>
                                            {member.email || member.username || `User ${member.id}`}
                                        </option>
                                    ))}
                                </select>
                            </div>
                        </div>

                        <div className="col-md-3">
                            <label className="settings-form-label">{t('auditLog.dateRange')}</label>
                            <div className="input-group">
                                <span className="input-group-text bg-white border-end-0"><FaCalendar className="text-muted" /></span>
                                <input
                                    type="date"
                                    className="form-control border-start-0 ps-0"
                                    value={filters.date_from}
                                    onChange={(e) => setFilters({ ...filters, date_from: e.target.value })}
                                />
                                <span className="input-group-text border-start-0 border-end-0 bg-white text-muted">{t('auditLog.to')}</span>
                                <input
                                    type="date"
                                    className="form-control border-start-0 ps-0"
                                    value={filters.date_to}
                                    onChange={(e) => setFilters({ ...filters, date_to: e.target.value })}
                                />
                            </div>
                        </div>

                        <div className="col-md-2">
                            <label className="settings-form-label">{t('auditLog.search')}</label>
                            <div className="input-group">
                                <span className="input-group-text bg-white border-end-0"><FaSearch className="text-muted" /></span>
                                <input
                                    type="text"
                                    className="form-control border-start-0 ps-0"
                                    placeholder={t('auditLog.searchPlaceholder')}
                                    value={filters.search}
                                    onChange={(e) => setFilters({ ...filters, search: e.target.value })}
                                />
                            </div>
                        </div>

                        <div className="col-md-3 d-flex gap-2">
                            <button type="submit" className="btn btn-primary flex-fill d-flex align-items-center justify-content-center">
                                {t('auditLog.searchBtn')}
                            </button>
                            <button
                                type="button"
                                className="btn btn-outline-secondary"
                                onClick={handleClearFilters}
                                title={t('auditLog.clearFilters')}
                            >
                                <FaTimes />
                            </button>
                            <button
                                type="button"
                                className="btn btn-outline-secondary"
                                onClick={handleExport}
                                disabled={exporting}
                                title={t('auditLog.exportCsv')}
                            >
                                {exporting ? <FaSpinner className="spin" /> : <FaDownload />}
                            </button>
                        </div>
                    </form>
                </div>
            </div>

            {/* Logs Table Card */}
            <div className="settings-card settings-card-flush">
                <div className="settings-card-body p-0 overflow-hidden">
                    {loading ? (
                        <div className="text-center py-5">
                            <FaSpinner className="spin text-primary mb-3" size={32} />
                            <p className="text-muted">{t('auditLog.loading')}</p>
                        </div>
                    ) : logs.length === 0 ? (
                        <div className="text-center py-5 text-muted">
                            <FaHistory size={48} className="mb-3 opacity-25" />
                            <h3>{t('auditLog.noLogs')}</h3>
                            <p>{t('auditLog.adjustFilters')}</p>
                        </div>
                    ) : (
                        <table className="table table-hover mb-0 align-middle">
                            <thead className="bg-light">
                                <tr>
                                    <th className="ps-4 py-3 border-0 text-uppercase small fw-bold text-muted">{t('auditLog.timestamp')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('auditLog.action')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('auditLog.user')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('auditLog.details')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('auditLog.ipAddress')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {logs.map((log) => {
                                    const ActionIcon = ACTION_ICONS[log.action] || FaCog;
                                    const colorClass = getActionColor(log.action);
                                    const isExpanded = expandedRows.has(log.id);
                                    const hasExpandable = hasDetails(log.details);

                                    return (
                                        <React.Fragment key={log.id}>
                                            <tr>
                                                <td className="ps-4 text-muted small whitespace-nowrap">
                                                    {formatDate(log.created_at)}
                                                </td>
                                                <td>
                                                    <span className={`badge bg-${colorClass}-subtle text-${colorClass} border border-${colorClass}-subtle rounded-pill px-3 py-2 d-inline-flex align-items-center gap-2`}>
                                                        <ActionIcon />
                                                        {log.action_display}
                                                    </span>
                                                </td>
                                                <td>
                                                    <div className="d-flex align-items-center gap-2">
                                                        <div className="avatar-xs bg-light rounded-circle d-flex align-items-center justify-content-center" style={{ width: 24, height: 24 }}>
                                                            <FaUser size={12} className="text-muted" />
                                                        </div>
                                                        <span className="fw-medium">{log.user}</span>
                                                    </div>
                                                </td>
                                                <td className="text-muted small text-break" style={{ maxWidth: '300px' }}>
                                                    <div className="d-flex align-items-start gap-2">
                                                        <span className="flex-grow-1">{summarizeDetails(log.details)}</span>
                                                        {hasExpandable && (
                                                            <button
                                                                type="button"
                                                                className="btn btn-link btn-sm p-0 text-muted"
                                                                onClick={() => toggleRow(log.id)}
                                                                aria-label={isExpanded ? t('auditLog.collapseDetails') : t('auditLog.expandDetails')}
                                                                aria-expanded={isExpanded}
                                                            >
                                                                {isExpanded ? <FaChevronUp /> : <FaChevronDown />}
                                                            </button>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="text-muted small font-monospace">
                                                    {log.ip_address || '-'}
                                                </td>
                                            </tr>
                                            {isExpanded && hasExpandable && (
                                                <tr>
                                                    <td colSpan={5} className="bg-light border-top-0 p-3">
                                                        <pre className="mb-0 small font-monospace text-body" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
{JSON.stringify(log.details, null, 2)}
                                                        </pre>
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Pagination Footer */}
                {pagination && pagination.total_pages > 1 && (
                    <div className="settings-card-footer d-flex justify-content-between align-items-center p-3 border-top bg-light">
                        <small className="text-muted">
                            {t('auditLog.showing', {
                                from: Math.min((pagination.page - 1) * pagination.page_size + 1, pagination.total),
                                to: Math.min(pagination.page * pagination.page_size, pagination.total),
                                total: pagination.total
                            })}
                        </small>
                        <div className="d-flex gap-2">
                            <button
                                className="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1"
                                onClick={() => setFilters({ ...filters, page: filters.page - 1 })}
                                disabled={filters.page <= 1}
                            >
                                <FaChevronLeft size={10} /> {t('auditLog.previous')}
                            </button>
                            <button
                                className="btn btn-outline-secondary btn-sm d-flex align-items-center gap-1"
                                onClick={() => setFilters({ ...filters, page: filters.page + 1 })}
                                disabled={filters.page >= pagination.total_pages}
                            >
                                {t('auditLog.next')} <FaChevronRight size={10} />
                            </button>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default AuditLogSettings;
