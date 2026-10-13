/**
 * ClusterPicker — header composed filter picker (Batch 54).
 *
 * The name is kept for backwards import compatibility, but the widget
 * now exposes the full DeploymentContext composed filter: cluster +
 * environment + region + namespace. Each dimension shows as a chip
 * with an inline clear button; a single dropdown lets the user pick
 * or edit any of them.
 *
 * Rendered when the org has 2+ clusters OR any composed filter is
 * already active. Single-cluster orgs with no filter see nothing —
 * progressive disclosure for SMB.
 */

import React, { useState } from 'react';
import { Dropdown, Form, InputGroup, Button, Badge } from 'react-bootstrap';
import {
    FaServer, FaChevronDown, FaTag, FaGlobe, FaCube,
    FaTimes, FaFilter,
} from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import { useDeployment } from '../context/DeploymentContext';

const ClusterPicker = () => {
    const { t } = useTranslation();
    const {
        clusters, hasMultiple, filter, setField, resetFilters,
        activeCount, currentCluster,
    } = useDeployment();
    const [envDraft, setEnvDraft] = useState('');
    const [regionDraft, setRegionDraft] = useState('');
    const [nsDraft, setNsDraft] = useState('');

    // Single-cluster org AND no composed filter active — hide.
    if (!hasMultiple && activeCount === 0) return null;

    const clusterLabel = currentCluster ? currentCluster.name : t('clusterPicker.all', 'All clusters');
    // Toggle label — show the most specific active chip or a summary.
    const toggleLabel = activeCount === 0
        ? clusterLabel
        : `${clusterLabel}${activeCount > 1 ? ` +${activeCount - (currentCluster ? 1 : 0)}` : ''}`;

    const applyEnv = () => { if (envDraft.trim()) { setField('environment', envDraft.trim()); setEnvDraft(''); } };
    const applyRegion = () => { if (regionDraft.trim()) { setField('region', regionDraft.trim()); setRegionDraft(''); } };
    const applyNs = () => {
        if (!filter.clusterId) return;
        if (nsDraft.trim()) { setField('namespace', nsDraft.trim()); setNsDraft(''); }
    };

    return (
        <div className="d-flex align-items-center gap-2">
            {/* Active-filter chips — inline, dismissible */}
            {filter.environment && (
                <FilterChip icon={<FaTag />} label={`env=${filter.environment}`}
                    onClear={() => setField('environment', '')} />
            )}
            {filter.region && (
                <FilterChip icon={<FaGlobe />} label={`region=${filter.region}`}
                    onClear={() => setField('region', '')} />
            )}
            {filter.namespace && (
                <FilterChip icon={<FaCube />} label={`ns=${filter.namespace}`}
                    onClear={() => setField('namespace', '')} />
            )}

            <Dropdown className="cluster-picker" autoClose="outside">
                <Dropdown.Toggle
                    variant="outline-secondary"
                    size="sm"
                    id="deployment-filter-toggle"
                    className="d-flex align-items-center"
                >
                    {activeCount > 0 ? <FaFilter className="me-2" /> : <FaServer className="me-2" />}
                    <span className="text-nowrap">{toggleLabel}</span>
                    {activeCount > 0 && (
                        <Badge bg="primary" pill className="ms-2">{activeCount}</Badge>
                    )}
                    <FaChevronDown className="ms-2" size={10} />
                </Dropdown.Toggle>
                <Dropdown.Menu style={{ minWidth: 280 }}>
                    {/* Cluster section */}
                    {hasMultiple && (
                        <>
                            <Dropdown.Header className="text-uppercase small text-muted">
                                <FaServer className="me-1" /> {t('clusterPicker.cluster', 'Cluster')}
                            </Dropdown.Header>
                            <Dropdown.Item
                                active={filter.clusterId == null}
                                onClick={() => setField('clusterId', null)}
                            >
                                {t('clusterPicker.all', 'All clusters')}
                            </Dropdown.Item>
                            {clusters.map((c) => (
                                <Dropdown.Item
                                    key={c.id}
                                    active={c.id === filter.clusterId}
                                    onClick={() => setField('clusterId', c.id)}
                                    disabled={!c.is_active}
                                >
                                    <span className="fw-medium">{c.name}</span>
                                    <span className="text-muted small ms-2">({c.provider_display})</span>
                                </Dropdown.Item>
                            ))}
                            <Dropdown.Divider />
                        </>
                    )}

                    {/* Env / region / namespace text filters */}
                    <div className="px-3 py-2">
                        <ScopeInput
                            icon={<FaTag />}
                            label={t('deploymentFilter.env', 'Environment')}
                            placeholder="production"
                            value={envDraft}
                            onChange={setEnvDraft}
                            onApply={applyEnv}
                        />
                        <ScopeInput
                            icon={<FaGlobe />}
                            label={t('deploymentFilter.region', 'Region')}
                            placeholder="us-east-1"
                            value={regionDraft}
                            onChange={setRegionDraft}
                            onApply={applyRegion}
                        />
                        <ScopeInput
                            icon={<FaCube />}
                            label={t('deploymentFilter.namespace', 'Namespace')}
                            placeholder={filter.clusterId ? 'payments' : t('deploymentFilter.nsNeedsCluster', 'select a cluster first')}
                            value={nsDraft}
                            onChange={setNsDraft}
                            onApply={applyNs}
                            disabled={!filter.clusterId}
                        />
                    </div>

                    {activeCount > 0 && (
                        <>
                            <Dropdown.Divider />
                            <div className="px-3 py-1 d-flex justify-content-end">
                                <Button variant="link" size="sm" className="p-0" onClick={resetFilters}>
                                    {t('deploymentFilter.clearAll', 'Clear all filters')}
                                </Button>
                            </div>
                        </>
                    )}
                </Dropdown.Menu>
            </Dropdown>
        </div>
    );
};

const FilterChip = ({ icon, label, onClear }) => (
    <span className="d-inline-flex align-items-center gap-1 badge rounded-pill bg-primary bg-opacity-10 text-primary px-2 py-1 border border-primary border-opacity-25">
        <span style={{ fontSize: 10 }}>{icon}</span>
        <span style={{ fontSize: 11 }}>{label}</span>
        <button
            type="button"
            className="btn btn-sm p-0 ms-1 lh-1 text-primary"
            style={{ fontSize: 10 }}
            onClick={onClear}
            aria-label="Clear filter"
        >
            <FaTimes />
        </button>
    </span>
);

const ScopeInput = ({ icon, label, placeholder, value, onChange, onApply, disabled }) => (
    <div className="mb-2">
        <div className="small text-muted mb-1 d-flex align-items-center gap-1">{icon} {label}</div>
        <InputGroup size="sm">
            <Form.Control
                type="text"
                placeholder={placeholder}
                value={value}
                disabled={disabled}
                onChange={(e) => onChange(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') onApply(); }}
            />
            <Button variant="outline-secondary" onClick={onApply} disabled={disabled || !value.trim()}>
                Set
            </Button>
        </InputGroup>
    </div>
);

export default ClusterPicker;
