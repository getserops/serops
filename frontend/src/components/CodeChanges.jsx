import React, { useState, useEffect } from "react";
import { Dropdown } from "react-bootstrap";
import { useParams } from "react-router-dom";
import { FiGitCommit, FiUser, FiClock, FiFile } from "react-icons/fi";
import { FaCodeBranch } from "react-icons/fa";
import PageHeader from "./PageHeader";
import { useTranslation } from "react-i18next";
import DataService from "../services/data.service";
import "./Data.css";

const CodeChanges = () => {
    const { t } = useTranslation();
    const { batchId } = useParams();
    const [codeChanges, setCodeChanges] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filters, setFilters] = useState({
        branch: "All Branches",
        author: "All Authors",
    });

    useEffect(() => {
        const fetchCodeChanges = async () => {
            try {
                setLoading(true);
                if (!batchId) return;

                const response = await DataService.getBatchCodeChanges(batchId);

                if (response?.results) {
                    setCodeChanges(response.results);
                }
            } catch (error) {
                console.error("Failed to fetch code changes:", error);
                setCodeChanges([]);
            } finally {
                setLoading(false);
            }
        };

        fetchCodeChanges();
    }, [batchId]);

    const formatTimestamp = (timestamp) => {
        if (!timestamp) return "N/A";
        try {
            return new Date(timestamp).toLocaleString();
        } catch {
            return timestamp;
        }
    };

    // Get unique branches and authors for filters
    const branches = [t('codeChanges.allBranches'), ...new Set(codeChanges.map(c => c.branch).filter(Boolean))];
    const authors = [t('codeChanges.allAuthors'), ...new Set(codeChanges.map(c => c.author).filter(Boolean))];

    // Apply filters
    const filteredChanges = codeChanges.filter(change => {
        if (filters.branch !== "All Branches" && filters.branch !== t('codeChanges.allBranches') && change.branch !== filters.branch) return false;
        if (filters.author !== "All Authors" && filters.author !== t('codeChanges.allAuthors') && change.author !== filters.author) return false;
        return true;
    });

    const handleFilterChange = (key, value) => {
        setFilters(prev => ({ ...prev, [key]: value }));
    };

    // Calculate stats
    const totalCommits = filteredChanges.length;
    const totalAdditions = filteredChanges.reduce((sum, c) => sum + (c.stats?.additions || 0), 0);
    const totalDeletions = filteredChanges.reduce((sum, c) => sum + (c.stats?.deletions || 0), 0);
    const totalFilesChanged = filteredChanges.reduce((sum, c) => sum + (c.stats?.files || 0), 0);

    if (loading) {
        return (
            <div className="data-page-container">
                <div className="data-card p-5 text-center">
                    <div className="spinner-border text-primary" role="status">
                        <span className="visually-hidden">{t('common.loading')}</span>
                    </div>
                    <p className="mt-2 text-muted">{t('codeChanges.loading')}</p>
                </div>
            </div>
        );
    }

    const shortBatch = batchId && (batchId.length <= 24 ? batchId : `${batchId.slice(0, 8)}…${batchId.slice(-6)}`);
    const filterLabel = (key, all, allLabel) => (filters[key] === all ? allLabel : filters[key]);

    return (
        <div className="data-page-container code-changes-page">
            <PageHeader
                crumbs={[
                    { label: t('nav.analyses'), to: '/dash/data' },
                    ...(batchId ? [{ label: shortBatch, to: `/dash/data/details/${batchId}`, mono: true }] : []),
                    { label: t('codeChanges.title') },
                ]}
                title={t('codeChanges.title')}
                badges={<span className="badge ds-chip ds-chip-neutral">{totalCommits}</span>}
                actions={
                    <>
                        <Dropdown onSelect={(value) => handleFilterChange("branch", value)} className="filter-dropdown">
                            <Dropdown.Toggle variant="light" className="d-flex align-items-center justify-content-between gap-2">
                                {t('codeChanges.branch')}: {filterLabel('branch', 'All Branches', t('codeChanges.allBranches'))}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                {branches.map((branch) => (
                                    <Dropdown.Item key={branch} eventKey={branch}>{branch}</Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                        <Dropdown onSelect={(value) => handleFilterChange("author", value)} className="filter-dropdown">
                            <Dropdown.Toggle variant="light" className="d-flex align-items-center justify-content-between gap-2">
                                {t('codeChanges.author')}: {filterLabel('author', 'All Authors', t('codeChanges.allAuthors'))}
                            </Dropdown.Toggle>
                            <Dropdown.Menu>
                                {authors.map((author) => (
                                    <Dropdown.Item key={author} eventKey={author}>{author}</Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                    </>
                }
            />

            {codeChanges.length === 0 ? (
                <div className="ds-section">
                    <div className="ds-empty-state">
                        <div className="ds-empty-state-icon"><FiGitCommit /></div>
                        <div className="ds-empty-state-title">{t('codeChanges.noChangesFound')}</div>
                        <div className="ds-empty-state-body">{t('codeChanges.noCommitsRecorded')}</div>
                    </div>
                </div>
            ) : (
                <>
                    <div className="cc-numbers">
                        <div className="cc-number">
                            <span className="cc-number-label">{t('codeChanges.totalCommits')}</span>
                            <span className="cc-number-value">{totalCommits}</span>
                        </div>
                        <div className="cc-number">
                            <span className="cc-number-label">{t('codeChanges.filesChanged')}</span>
                            <span className="cc-number-value">{totalFilesChanged}</span>
                        </div>
                        <div className="cc-number">
                            <span className="cc-number-label">{t('codeChanges.additions')}</span>
                            <span className="cc-number-value cc-add">+{totalAdditions}</span>
                        </div>
                        <div className="cc-number">
                            <span className="cc-number-label">{t('codeChanges.deletions')}</span>
                            <span className="cc-number-value cc-del">−{totalDeletions}</span>
                        </div>
                    </div>

                    <section className="ds-section">
                        <div className="ds-section-head">
                            <h2 className="ds-section-title">{t('codeChanges.recentCommits')}</h2>
                        </div>
                        <ul className="cc-list">
                            {filteredChanges.map((change, index) => (
                                <li key={change.id || index} className="cc-item">
                                    <div className="cc-main">
                                        <div className="cc-message">{change.message?.split('\n')[0] || t('codeChanges.noMessage')}</div>
                                        <div className="cc-meta">
                                            <code className="cc-sha">{change.sha ? change.sha.slice(0, 8) : 'N/A'}</code>
                                            <span className="cc-branch"><FaCodeBranch aria-hidden="true" /> {change.branch || t('codeChanges.unknown')}</span>
                                            {change.service_name && <span className="badge ds-chip ds-chip-neutral">{change.service_name}</span>}
                                            <span><FiUser aria-hidden="true" /> {change.author || t('codeChanges.unknown')}</span>
                                            <span><FiClock aria-hidden="true" /> {formatTimestamp(change.timestamp)}</span>
                                        </div>
                                    </div>
                                    <div className="cc-stats">
                                        <span className="cc-files"><FiFile aria-hidden="true" /> {change.stats?.files || 0} {t('codeChanges.files')}</span>
                                        <span className="cc-add">+{change.stats?.additions || 0}</span>
                                        <span className="cc-del">−{change.stats?.deletions || 0}</span>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    </section>
                </>
            )}
        </div>
    );
};

export default CodeChanges;
