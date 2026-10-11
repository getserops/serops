/**
 * WorkloadsByCluster — dashboard card showing what SerOps is watching
 * per cluster (Item #19).
 *
 * Rendered only when the org has 2+ clusters. Single-cluster orgs get
 * nothing (the existing dashboard already tells them everything).
 *
 * Each cluster row expands to show its projects + services. Uses the
 * `/api/integrations/clusters/<id>/workloads/` endpoint added in
 * backend Batch 18.
 */

import React, { useEffect, useState, useCallback } from 'react';
import { Card, Spinner, Badge, Accordion } from 'react-bootstrap';
import { FaServer, FaCubes } from 'react-icons/fa';
import { useTranslation } from 'react-i18next';
import { useCluster } from '../context/ClusterContext';
import ClusterService from '../services/cluster.service';

const ServiceRow = ({ svc }) => (
    <div className="d-flex align-items-center py-1">
        <FaCubes className="text-muted me-2" size={12} />
        <span className="me-2">{svc.name || `service #${svc.id}`}</span>
        <Badge bg="light" text="dark" className="me-1 small">
            {svc.service_type}
        </Badge>
        {svc.subtype && <span className="text-muted small">{svc.subtype}</span>}
    </div>
);

const ClusterCard = ({ cluster }) => {
    const [payload, setPayload] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                setLoading(true);
                const data = await ClusterService.workloads(cluster.id);
                if (!cancelled) setPayload(data);
            } catch {
                if (!cancelled) setPayload({ cluster, projects: [] });
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [cluster.id]);

    const projects = payload?.projects || [];
    const totalServices = projects.reduce((sum, p) => sum + (p.services?.length || 0), 0);

    return (
        <Accordion.Item eventKey={String(cluster.id)}>
            <Accordion.Header>
                <div className="d-flex align-items-center flex-grow-1 me-3">
                    <FaServer className={cluster.is_active ? 'text-primary me-2' : 'text-muted me-2'} />
                    <span className="fw-bold me-2">{cluster.name}</span>
                    <span className="text-muted small me-3">{cluster.provider_display}</span>
                    {loading ? (
                        <Spinner size="sm" animation="border" />
                    ) : (
                        <>
                            <Badge bg="secondary" className="me-2">
                                {projects.length} project{projects.length !== 1 ? 's' : ''}
                            </Badge>
                            <Badge bg="light" text="dark">
                                {totalServices} service{totalServices !== 1 ? 's' : ''}
                            </Badge>
                        </>
                    )}
                </div>
            </Accordion.Header>
            <Accordion.Body>
                {loading ? (
                    <Spinner size="sm" animation="border" />
                ) : projects.length === 0 ? (
                    <p className="text-muted small mb-0">
                        No projects assigned to this cluster yet.
                    </p>
                ) : (
                    projects.map((p) => (
                        <div key={p.id} className="mb-3">
                            <div className="fw-medium">{p.name}</div>
                            {p.description && (
                                <div className="text-muted small mb-1">{p.description}</div>
                            )}
                            {p.services.length === 0
                                ? <div className="text-muted small">— no services —</div>
                                : p.services.map((s) => <ServiceRow key={s.id} svc={s} />)}
                        </div>
                    ))
                )}
            </Accordion.Body>
        </Accordion.Item>
    );
};

const WorkloadsByCluster = () => {
    const { t } = useTranslation();
    const { clusters, hasMultiple, loading } = useCluster();

    // Single-cluster orgs skip this card entirely — the existing
    // per-project dashboard already covers everything.
    if (!hasMultiple || loading) return null;

    return (
        <Card className="mb-4">
            <Card.Header>
                <FaServer className="me-2 text-primary" />
                {t('workloadsByCluster.title')}
            </Card.Header>
            <Card.Body>
                <Accordion>
                    {clusters.map((c) => <ClusterCard key={c.id} cluster={c} />)}
                </Accordion>
            </Card.Body>
        </Card>
    );
};

export default WorkloadsByCluster;
