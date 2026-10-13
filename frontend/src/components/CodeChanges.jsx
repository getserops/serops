import React, { useState, useEffect } from "react";
import { Card, Container, Row, Col, Dropdown, Badge } from "react-bootstrap";
import { useNavigate, useParams } from "react-router-dom";
import { FiArrowLeft, FiGitCommit, FiUser, FiClock, FiFile } from "react-icons/fi";
import { FaCodeBranch, FaPlus, FaMinus } from "react-icons/fa";
import { useTranslation } from "react-i18next";
import DataService from "../services/data.service";
import "./Data.css";

const CodeChanges = () => {
    const { t } = useTranslation();
    const { batchId } = useParams();
    const navigate = useNavigate();
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

    return (
        <div className="data-page-container">
            <div className="data-card">
                {/* Header with filters */}
                <div className="data-toolbar justify-content-between">
                    <div className="d-flex align-items-center gap-3">
                        <button
                            onClick={() => navigate(-1)}
                            className="btn btn-outline-secondary d-flex align-items-center gap-2"
                        >
                            <FiArrowLeft />
                            {t('common.back')}
                        </button>
                        <h4 className="mb-0 fw-bold">{t('codeChanges.title')}</h4>
                        <Badge bg="primary" pill>
                            {totalCommits}
                        </Badge>
                    </div>

                    <div className="d-flex gap-3">
                        <Dropdown onSelect={(value) => handleFilterChange("branch", value)} className="filter-dropdown">
                            <Dropdown.Toggle variant="light" className="d-flex align-items-center justify-content-between gap-2">
                                {t('codeChanges.branch')}: {filters.branch === "All Branches" ? t('codeChanges.allBranches') : filters.branch}
                            </Dropdown.Toggle>
                            <Dropdown.Menu className="shadow-sm border-0">
                                {branches.map((branch) => (
                                    <Dropdown.Item key={branch} eventKey={branch}>
                                        {branch}
                                    </Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                        <Dropdown onSelect={(value) => handleFilterChange("author", value)} className="filter-dropdown">
                            <Dropdown.Toggle variant="light" className="d-flex align-items-center justify-content-between gap-2">
                                {t('codeChanges.author')}: {filters.author === "All Authors" ? t('codeChanges.allAuthors') : filters.author}
                            </Dropdown.Toggle>
                            <Dropdown.Menu className="shadow-sm border-0">
                                {authors.map((author) => (
                                    <Dropdown.Item key={author} eventKey={author}>
                                        {author}
                                    </Dropdown.Item>
                                ))}
                            </Dropdown.Menu>
                        </Dropdown>
                    </div>
                </div>

                <div className="p-4">
                    {codeChanges.length === 0 ? (
                        <div className="ds-empty-state">
                            <div className="ds-empty-state-icon">
                                <FiGitCommit />
                            </div>
                            <div className="ds-empty-state-title">
                                {t('codeChanges.noChangesFound')}
                            </div>
                            <div className="ds-empty-state-body">
                                {t('codeChanges.noCommitsRecorded')}
                            </div>
                        </div>
                    ) : (
                        <>
                            {/* Stats Row */}
                            <Row className="g-4 mb-4">
                                <Col md={3}>
                                    <div className="p-3 text-center rounded-3 bg-light border-0 h-100">
                                        <FiGitCommit size={24} className="mx-auto mb-2" style={{ color: "#4e73df" }} />
                                        <h3 className="fw-bold" style={{ color: "#4e73df" }}>{totalCommits}</h3>
                                        <small className="text-muted text-uppercase fw-bold" style={{ fontSize: '0.75rem' }}>{t('codeChanges.totalCommits')}</small>
                                    </div>
                                </Col>
                                <Col md={3}>
                                    <div className="p-3 text-center rounded-3 bg-light border-0 h-100">
                                        <FiFile size={24} className="mx-auto mb-2" style={{ color: "#858796" }} />
                                        <h3 className="fw-bold" style={{ color: "#858796" }}>{totalFilesChanged}</h3>
                                        <small className="text-muted text-uppercase fw-bold" style={{ fontSize: '0.75rem' }}>{t('codeChanges.filesChanged')}</small>
                                    </div>
                                </Col>
                                <Col md={3}>
                                    <div className="p-3 text-center rounded-3 border-0 h-100" style={{ backgroundColor: "rgba(28, 200, 138, 0.1)" }}>
                                        <FaPlus size={24} className="mx-auto mb-2" style={{ color: "#1cc88a" }} />
                                        <h3 className="fw-bold" style={{ color: "#1cc88a" }}>+{totalAdditions}</h3>
                                        <small className="text-muted text-uppercase fw-bold" style={{ fontSize: '0.75rem' }}>{t('codeChanges.additions')}</small>
                                    </div>
                                </Col>
                                <Col md={3}>
                                    <div className="p-3 text-center rounded-3 border-0 h-100" style={{ backgroundColor: "rgba(231, 74, 59, 0.1)" }}>
                                        <FaMinus size={24} className="mx-auto mb-2" style={{ color: "#e74a3b" }} />
                                        <h3 className="fw-bold" style={{ color: "#e74a3b" }}>-{totalDeletions}</h3>
                                        <small className="text-muted text-uppercase fw-bold" style={{ fontSize: '0.75rem' }}>{t('codeChanges.deletions')}</small>
                                    </div>
                                </Col>
                            </Row>

                            {/* Commits List */}
                            <h6 className="text-muted mb-3 fw-bold text-uppercase small">{t('codeChanges.recentCommits')}</h6>
                            <div className="border rounded-3 overflow-hidden">
                                {filteredChanges.map((change, index) => (
                                    <div
                                        key={change.id || index}
                                        className={`p-3 ${index !== filteredChanges.length - 1 ? 'border-bottom' : ''}`}
                                        style={{ backgroundColor: index % 2 === 0 ? '#fff' : '#f8f9fc' }}
                                    >
                                        <div className="d-flex justify-content-between align-items-start">
                                            {/* Left side - Commit info */}
                                            <div className="flex-grow-1">
                                                <div className="d-flex align-items-center mb-2">
                                                    <code
                                                        className="px-2 py-1 rounded me-2"
                                                        style={{
                                                            backgroundColor: '#4e73df',
                                                            color: '#fff',
                                                            fontSize: '12px',
                                                            fontFamily: 'monospace'
                                                        }}
                                                    >
                                                        {change.sha || 'N/A'}
                                                    </code>
                                                    <Badge bg="info" className="me-2 text-white">
                                                        {change.branch || t('codeChanges.unknown')}
                                                    </Badge>
                                                    {change.service_name && (
                                                        <Badge bg="secondary" className="me-2">
                                                            {change.service_name}
                                                        </Badge>
                                                    )}
                                                </div>
                                                <div style={{ fontSize: '15px', fontWeight: 600, marginBottom: '6px', color: '#2c3e50' }}>
                                                    {change.message?.split('\n')[0] || t('codeChanges.noMessage')}
                                                </div>
                                                <div className="text-muted d-flex align-items-center" style={{ fontSize: '13px' }}>
                                                    <FiUser className="me-1" />
                                                    <span className="fw-medium me-2">{change.author || t('codeChanges.unknown')}</span>
                                                    <span className="mx-2 text-gray-300">•</span>
                                                    <FiClock className="me-1" />
                                                    {formatTimestamp(change.timestamp)}
                                                </div>
                                            </div>

                                            {/* Right side - Stats */}
                                            <div className="text-end" style={{ minWidth: '120px' }}>
                                                <div className="mb-1" style={{ fontSize: '13px' }}>
                                                    <FiFile className="me-1 text-muted" />
                                                    <span className="fw-medium">{change.stats?.files || 0} {t('codeChanges.files')}</span>
                                                </div>
                                                <div style={{ fontSize: '13px' }}>
                                                    <span className="text-success me-2 fw-bold">
                                                        <FaPlus className="me-1" size={10} />
                                                        {change.stats?.additions || 0}
                                                    </span>
                                                    <span className="text-danger fw-bold">
                                                        <FaMinus className="me-1" size={10} />
                                                        {change.stats?.deletions || 0}
                                                    </span>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default CodeChanges;
