/**
 * Observability Provider Panels — multi-row list with scope + tier (Batch 53).
 *
 * Rewritten from the single-integration-per-capability shape to a
 * per-row list. Each row surfaces provider + scope pills (env, cluster,
 * region, namespace) + tier badge (primary/fallback/tertiary) + health
 * status. The edit form is a modal so the row list stays scannable.
 *
 * Progressive disclosure for SMB: single-integration orgs still see a
 * one-row list — the mental cost of "list vs single" is small and buys
 * us the ability to model multi-region / multi-tier / multi-cluster
 * without a schema jump later.
 *
 * Exports:
 *   - LogProviderPanel      — Log Providers tab
 *   - MetricProviderPanel   — Metric Providers tab
 *   - default               — full ObservabilitySettings page
 */

import React, { useState, useEffect } from "react";
import { Modal, Button, Form } from "react-bootstrap";
import { toast } from "react-toastify";
import {
    SiElasticsearch,
    SiGrafana,
    SiPrometheus,
    SiDatadog,
    SiAmazonwebservices,
    SiOpensearch,
} from "react-icons/si";
import {
    FaChartLine, FaCheck, FaTimes, FaSpinner, FaPlug, FaTrash,
    FaServer, FaPlus, FaEdit, FaTag, FaGlobe, FaCube,
} from "react-icons/fa";
import ObservabilityService from "../../services/observability.service";
import ClusterService from "../../services/cluster.service";
import ChoiceGroup from "./ChoiceGroup";
import IntegrationsSectionHeader from "./IntegrationsSectionHeader";
import { usePermissions } from "../../utils/permissions";

/* ─── Provider Metadata ──────────────────────────────────────────────── */

const PROVIDERS = {
    elasticsearch: {
        name: "Elasticsearch", icon: SiElasticsearch, color: "#FEC514",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "Host URL", type: "url", placeholder: "http://elasticsearch:9200", required: true },
            { name: "username", label: "Username", placeholder: "elastic" },
            { name: "password", label: "Password", type: "password" },
        ],
    },
    opensearch: {
        name: "OpenSearch", icon: SiOpensearch, color: "#005EB8",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "Host URL", type: "url", placeholder: "https://opensearch:9200", required: true },
            { name: "username", label: "Username" },
            { name: "password", label: "Password", type: "password" },
        ],
    },
    loki: {
        name: "Grafana Loki", icon: SiGrafana, color: "#F46800",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "Loki URL", type: "url", placeholder: "http://loki:3100", required: true },
            { name: "extra_config.tenant_id", label: "Tenant ID", placeholder: "default" },
        ],
    },
    prometheus: {
        name: "Prometheus", icon: SiPrometheus, color: "#E6522C",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "Prometheus URL", type: "url", placeholder: "http://prometheus:9090", required: true },
            { name: "username", label: "Username", placeholder: "optional" },
            { name: "password", label: "Password", type: "password" },
            { name: "extra_config.bearer_token", label: "Bearer Token", type: "password", placeholder: "For Grafana Cloud, Thanos, etc." },
        ],
    },
    promscale: {
        name: "Promscale", icon: SiPrometheus, color: "#4E73DF",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "Promscale URL", type: "url", placeholder: "http://promscale:9201", required: true },
        ],
    },
    victoriametrics: {
        name: "VictoriaMetrics", icon: FaChartLine, color: "#621773",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "VM URL", type: "url", placeholder: "http://victoria:8428", required: true },
            { name: "username", label: "Username", placeholder: "optional" },
            { name: "password", label: "Password", type: "password" },
            { name: "extra_config.bearer_token", label: "Bearer Token", type: "password", placeholder: "For managed VM Cloud" },
        ],
    },
    mimir: {
        name: "Grafana Mimir", icon: SiGrafana, color: "#FF5733",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "Mimir URL", type: "url", placeholder: "http://mimir:9009", required: true },
            { name: "extra_config.tenant_id", label: "Tenant ID", placeholder: "default" },
            { name: "username", label: "Username", placeholder: "optional" },
            { name: "password", label: "Password", type: "password" },
            { name: "extra_config.bearer_token", label: "Bearer Token", type: "password", placeholder: "For Grafana Cloud" },
        ],
    },
    datadog: {
        name: "Datadog", icon: SiDatadog, color: "#632CA6",
        capabilities: ["logs", "metrics"],
        fields: [
            { name: "host", label: "Datadog Site", placeholder: "datadoghq.com", required: true },
            { name: "extra_config.api_key", label: "API Key", type: "password", required: true },
            { name: "extra_config.app_key", label: "Application Key", type: "password" },
        ],
    },
    cloudwatch: {
        name: "AWS CloudWatch", icon: SiAmazonwebservices, color: "#FF9900",
        capabilities: ["logs", "metrics"],
        fields: [
            { name: "extra_config.aws_region", label: "AWS Region", placeholder: "us-east-1", required: true },
            { name: "username", label: "Access Key ID", required: true },
            { name: "password", label: "Secret Access Key", type: "password", required: true },
        ],
    },
};

// Chip tones from the design system (styles/design.css · Badges).
const TIER_META = {
    primary:  { label: "Primary",  tone: "ds-chip-brand" },
    fallback: { label: "Fallback", tone: "ds-chip-warn" },
    tertiary: { label: "Tertiary", tone: "ds-chip-neutral" },
};
const TIER_ORDER = { primary: 0, fallback: 1, tertiary: 2 };

/* ─── Helper: resolve nested field paths ─────────────────────────────── */

function getNestedValue(obj, path) {
    return path.split(".").reduce((o, key) => (o ? o[key] : ""), obj);
}
function setNestedValue(obj, path, value) {
    const clone = JSON.parse(JSON.stringify(obj));
    const keys = path.split(".");
    let current = clone;
    keys.forEach((key, i) => {
        if (i === keys.length - 1) current[key] = value;
        else {
            if (!current[key] || typeof current[key] !== "object") current[key] = {};
            current = current[key];
        }
    });
    return clone;
}

/* ─── Small display atoms ────────────────────────────────────────────── */

function CapBadge({ cap }) {
    return (
        <span className={`ds-chip ${cap === "logs" ? "ds-chip-ok" : "ds-chip-info"}`}>
            {cap === "logs" ? "Logs" : "Metrics"}
        </span>
    );
}

function StatusBadge({ status }) {
    if (status === true)  return <span className="obs-status" style={{ color: "var(--tone-green-text)" }}><FaCheck /> Healthy</span>;
    if (status === false) return <span className="obs-status" style={{ color: "var(--tone-red-text)" }}><FaTimes /> Unhealthy</span>;
    return <span className="obs-status" style={{ color: "var(--text-tertiary)" }}>—</span>;
}

function TierBadge({ tier }) {
    const meta = TIER_META[tier] || TIER_META.primary;
    return <span className={`ds-chip ${meta.tone}`}>{meta.label}</span>;
}

function ScopePills({ integration, clusterName }) {
    const scope = integration.scope || {};
    const items = [];
    if (scope.environment) items.push({ icon: <FaTag size={9} />, key: "env", val: scope.environment, tone: "ds-chip-brand" });
    if (clusterName)       items.push({ icon: <FaServer size={9} />, key: "cluster", val: clusterName, tone: "ds-chip-info" });
    if (scope.region)      items.push({ icon: <FaGlobe size={9} />, key: "region", val: scope.region, tone: "ds-chip-neutral" });
    if (scope.namespace)   items.push({ icon: <FaCube size={9} />, key: "ns", val: scope.namespace, tone: "ds-chip-warn" });
    if (items.length === 0) {
        return <span className="obs-unscoped">unscoped — serves any</span>;
    }
    return (
        <div className="obs-scope-pills">
            {items.map((p) => (
                <span key={p.key} className={`ds-chip ${p.tone}`}>{p.icon}{p.key}={p.val}</span>
            ))}
        </div>
    );
}

/* ─── Integration Form Modal (create + edit) ─────────────────────────── */

function IntegrationFormModal({ show, onHide, capability, integration, clusters, onSaved }) {
    const isEdit = !!integration;
    const [selectedProvider, setSelectedProvider] = useState(null);
    const [form, setForm] = useState({});
    const [enabledCaps, setEnabledCaps] = useState([capability]);
    const [clusterId, setClusterId] = useState(null);
    const [tier, setTier] = useState("primary");
    const [scope, setScope] = useState({ environment: "", region: "", namespace: "" });
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);

    // Providers relevant to this tab
    const filteredProviders = Object.entries(PROVIDERS).filter(
        ([, meta]) => meta.capabilities.includes(capability)
    );

    // Prime form when opened
    useEffect(() => {
        if (!show) return;
        if (isEdit && integration) {
            setSelectedProvider(integration.provider);
            setEnabledCaps(integration.capabilities || [capability]);
            setClusterId(integration.cluster ?? null);
            setTier(integration.priority_tier || "primary");
            setScope({
                environment: integration.scope?.environment || "",
                region: integration.scope?.region || "",
                namespace: integration.scope?.namespace || "",
            });
            setForm({
                host: integration.host || "",
                username: integration.username || "",
                extra_config: integration.extra_config || {},
            });
        } else {
            setSelectedProvider(null);
            setEnabledCaps([capability]);
            setClusterId(null);
            setTier("primary");
            setScope({ environment: "", region: "", namespace: "" });
            setForm({});
        }
    }, [show, integration, isEdit, capability]);

    const providerMeta = selectedProvider ? PROVIDERS[selectedProvider] : null;

    function handleSelectProvider(code) {
        setSelectedProvider(code);
        setForm({});
        const meta = PROVIDERS[code];
        setEnabledCaps(meta.capabilities.length > 1 ? [...meta.capabilities] : meta.capabilities);
    }

    function handleFieldChange(fieldPath, value) {
        if (fieldPath.includes("."))
            setForm((prev) => setNestedValue(prev, fieldPath, value));
        else
            setForm((prev) => ({ ...prev, [fieldPath]: value }));
    }

    function toggleCap(cap) {
        setEnabledCaps((prev) => {
            if (prev.includes(cap)) {
                const next = prev.filter((c) => c !== cap);
                return next.length > 0 ? next : prev;
            }
            return [...prev, cap];
        });
    }

    async function handleSave() {
        if (!selectedProvider) return;
        // Namespace-requires-cluster mirrors the backend check —
        // stop the user before the round-trip.
        if (scope.namespace && !clusterId) {
            toast.error("Namespace can only be set when a cluster is selected.");
            return;
        }
        setSaving(true);
        try {
            const payload = {
                provider: selectedProvider,
                display_name: PROVIDERS[selectedProvider].name,
                capabilities: enabledCaps,
                is_active: true,
                host: form.host || "",
                username: form.username || "",
                extra_config: form.extra_config || {},
                cluster: clusterId,
                priority_tier: tier,
                scope: {
                    environment: scope.environment || "",
                    region: scope.region || "",
                    namespace: scope.namespace || "",
                },
            };
            if (form.password) payload.password = form.password;

            if (isEdit) {
                await ObservabilityService.update(integration.id, payload);
                toast.success("Integration updated");
            } else {
                await ObservabilityService.create(payload);
                toast.success("Integration created");
            }
            onSaved();
            onHide();
        } catch (err) {
            const data = err.response?.data;
            const msg = data?.detail
                || data?.provider?.[0]
                || data?.capabilities?.[0]
                || data?.non_field_errors?.[0]
                || data?.scope?.namespace?.[0]
                || "Failed to save integration";
            toast.error(msg);
        } finally {
            setSaving(false);
        }
    }

    async function handleTest() {
        if (!isEdit) {
            toast.info("Save the integration first, then test.");
            return;
        }
        setTesting(true);
        try {
            const result = await ObservabilityService.healthCheck(integration.id);
            const allOk = result.integrations?.every((r) => r.healthy);
            if (allOk) toast.success("Connection healthy");
            else {
                const failing = result.integrations?.filter((r) => !r.healthy);
                toast.error(`Health check failed: ${failing?.map((r) => r.message).join(", ")}`);
            }
            onSaved();
        } catch {
            toast.error("Connection test failed");
        } finally {
            setTesting(false);
        }
    }

    return (
        <Modal show={show} onHide={onHide} size="lg" centered>
            <Modal.Header closeButton>
                <Modal.Title>
                    {isEdit ? `Edit ${PROVIDERS[integration.provider]?.name || 'integration'}`
                            : `New ${capability === 'logs' ? 'log' : 'metric'} provider`}
                </Modal.Title>
            </Modal.Header>
            <Modal.Body>
                {/* Provider grid — disabled when editing (provider is immutable) */}
                <ChoiceGroup
                    variant="cards"
                    className="mb-3"
                    label="Provider"
                    value={selectedProvider}
                    onChange={handleSelectProvider}
                    options={filteredProviders.map(([code, meta]) => ({
                        value: code,
                        // The provider can't change once an integration exists.
                        disabled: isEdit && code !== integration.provider,
                        label: <span className="d-inline-flex align-items-center gap-2">{React.createElement(meta.icon, { size: 18, color: meta.color, "aria-hidden": true })}{meta.name}</span>,
                    }))}
                />

                {providerMeta && (
                    <>
                        {/* Priority tier + cluster + scope */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                            <Form.Group controlId="obs-tier">
                                <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>Priority tier</Form.Label>
                                <Form.Select value={tier} onChange={(e) => setTier(e.target.value)} size="sm">
                                    <option value="primary">Primary — tried first</option>
                                    <option value="fallback">Fallback — on primary error</option>
                                    <option value="tertiary">Tertiary — last resort</option>
                                </Form.Select>
                            </Form.Group>
                            {clusters.length > 0 && (
                                <Form.Group controlId="obs-cluster">
                                    <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>
                                        <FaServer style={{ marginRight: 4 }} />Cluster scope
                                    </Form.Label>
                                    <Form.Select
                                        value={clusterId ?? ""}
                                        onChange={(e) => setClusterId(e.target.value ? parseInt(e.target.value, 10) : null)}
                                        size="sm"
                                    >
                                        <option value="">Unscoped — serves any cluster</option>
                                        {clusters.map((c) => (
                                            <option key={c.id} value={c.id}>
                                                {c.name} — {c.provider_display}{c.region ? ` (${c.region})` : ""}
                                            </option>
                                        ))}
                                    </Form.Select>
                                </Form.Group>
                            )}
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16, padding: 12, background: "var(--bg-sunken)", borderRadius: 6 }}>
                            <Form.Group controlId="obs-env">
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)" }}>
                                    <FaTag size={10} style={{ marginRight: 4 }} />Environment
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="production"
                                    value={scope.environment}
                                    onChange={(e) => setScope({ ...scope, environment: e.target.value })} />
                            </Form.Group>
                            <Form.Group controlId="obs-region">
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)" }}>
                                    <FaGlobe size={10} style={{ marginRight: 4 }} />Region
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="us-east-1"
                                    value={scope.region}
                                    onChange={(e) => setScope({ ...scope, region: e.target.value })} />
                            </Form.Group>
                            <Form.Group controlId="obs-namespace">
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)" }}>
                                    <FaCube size={10} style={{ marginRight: 4 }} />Namespace
                                    {!clusterId && <span style={{ marginLeft: 4, fontSize: 9, color: "var(--text-tertiary)" }}>(needs cluster)</span>}
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="payments"
                                    value={scope.namespace}
                                    disabled={!clusterId}
                                    onChange={(e) => setScope({ ...scope, namespace: e.target.value })} />
                            </Form.Group>
                        </div>

                        {/* Capabilities toggles for dual-cap providers */}
                        {providerMeta.capabilities.length > 1 && (
                            <div style={{ marginBottom: 14, padding: 10, backgroundColor: "var(--bg-sunken)", borderRadius: 6 }}>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginRight: 10 }}>Capabilities:</span>
                                {providerMeta.capabilities.map((cap) => (
                                    <label key={cap} style={{ marginRight: 14, cursor: "pointer", fontSize: 13 }}>
                                        <input type="checkbox" checked={enabledCaps.includes(cap)}
                                            onChange={() => toggleCap(cap)} style={{ marginRight: 4 }} />
                                        {cap === "logs" ? "Log Provider" : "Metric Provider"}
                                    </label>
                                ))}
                            </div>
                        )}

                        {/* Provider-specific connection fields */}
                        {providerMeta.fields.map((field) => {
                            const isSecret = field.type === "password";
                            const hasStoredValue = isSecret && isEdit && (
                                field.name === "password"
                                    ? integration?.has_password
                                    : (integration?.secret_fields_set || []).includes(field.name.replace("extra_config.", ""))
                            );
                            const placeholder = hasStoredValue && !getNestedValue(form, field.name)
                                ? "••••••••  (leave blank to keep)"
                                : (field.placeholder || "");
                            return (
                                <Form.Group key={field.name} controlId={`obs-${field.name}`} style={{ marginBottom: 12 }}>
                                    <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>
                                        {field.label} {field.required && <span style={{ color: "var(--tone-red-text)" }}>*</span>}
                                    </Form.Label>
                                    <Form.Control type={field.type || "text"} size="sm"
                                        placeholder={placeholder}
                                        value={getNestedValue(form, field.name) || ""}
                                        onChange={(e) => handleFieldChange(field.name, e.target.value)} />
                                </Form.Group>
                            );
                        })}
                    </>
                )}
            </Modal.Body>
            <Modal.Footer>
                {isEdit && (
                    <Button variant="outline-primary" size="sm" onClick={handleTest} disabled={testing} className="me-auto">
                        {testing ? <><FaSpinner className="spin" /> Testing…</> : <><FaPlug /> Test</>}
                    </Button>
                )}
                <Button variant="secondary" onClick={onHide} size="sm">Cancel</Button>
                <Button variant="primary" onClick={handleSave} disabled={saving || !selectedProvider} size="sm">
                    {saving ? <><FaSpinner className="spin" /> Saving…</> : (isEdit ? "Update" : "Create")}
                </Button>
            </Modal.Footer>
        </Modal>
    );
}

/* ─── Integration Row + List ─────────────────────────────────────────── */

function IntegrationRow({ integration, clusters, onEdit, onDelete }) {
    const meta = PROVIDERS[integration.provider];
    const Icon = meta?.icon || FaChartLine;
    const clusterName = clusters.find((c) => c.id === integration.cluster)?.name;

    return (
        <div className="obs-integration-row">
            <Icon size={22} color={meta?.color || "var(--text-secondary)"} style={{ flexShrink: 0 }} aria-hidden="true" />
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span className="obs-integration-name">
                        {integration.display_name || meta?.name || integration.provider}
                    </span>
                    <TierBadge tier={integration.priority_tier} />
                    {integration.capabilities?.map((c) => <CapBadge key={c} cap={c} />)}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <ScopePills integration={integration} clusterName={clusterName} />
                </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                <StatusBadge status={integration.last_health_status} />
                {onEdit && (
                    <Button variant="outline-secondary" size="sm" onClick={() => onEdit(integration)} title="Edit" aria-label="Edit">
                        <FaEdit size={12} />
                    </Button>
                )}
                {onDelete && (
                    <Button variant="outline-danger" size="sm" onClick={() => onDelete(integration)} title="Delete" aria-label="Delete">
                        <FaTrash size={12} />
                    </Button>
                )}
            </div>
        </div>
    );
}

function ProviderPanel({ capability, integrations, onRefresh }) {
    // Sources hold credentials: only admins add, edit or delete them (the API enforces it).
    const canManage = usePermissions()("integration.manage");
    const [clusters, setClusters] = useState([]);
    const [showModal, setShowModal] = useState(false);
    const [editingRow, setEditingRow] = useState(null);

    useEffect(() => {
        ClusterService.list()
            .then((rows) => setClusters(Array.isArray(rows) ? rows.filter((c) => c.is_active) : []))
            .catch(() => setClusters([]));
    }, []);

    const rows = integrations
        .filter((i) => i.capabilities?.includes(capability) && i.is_active)
        .sort((a, b) => {
            const ta = TIER_ORDER[a.priority_tier] ?? 99;
            const tb = TIER_ORDER[b.priority_tier] ?? 99;
            if (ta !== tb) return ta - tb;
            return (a.created_at || "").localeCompare(b.created_at || "");
        });

    async function handleDelete(row) {
        const label = row.display_name || PROVIDERS[row.provider]?.name || row.provider;
        if (!window.confirm(`Remove the ${row.priority_tier} ${label} integration?`)) return;
        try {
            await ObservabilityService.delete(row.id);
            toast.success("Integration removed");
            onRefresh();
        } catch {
            toast.error("Failed to remove integration");
        }
    }

    function openCreate() { setEditingRow(null); setShowModal(true); }
    function openEdit(row) { setEditingRow(row); setShowModal(true); }

    return (
        <div>
            <IntegrationsSectionHeader
                title={capability === "logs" ? "Log Providers" : "Metric Providers"}
                count={rows.length}
                description="Ordered by priority tier. The batch pipeline tries primary first, then fallback, then tertiary."
                action={canManage && (
                    <Button variant="primary" onClick={openCreate}>
                        <FaPlus aria-hidden="true" /> Add {capability === "logs" ? "log" : "metric"} provider
                    </Button>
                )}
            />

            {rows.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaPlug size={40} className="mb-2 opacity-50" />
                    <p>No {capability === "logs" ? "log" : "metric"} providers configured yet.</p>
                    <p className="small">Using system default until you add one.</p>
                </div>
            ) : (
                <div>
                    {rows.map((row) => (
                        <IntegrationRow key={row.id} integration={row} clusters={clusters}
                            onEdit={canManage ? openEdit : undefined} onDelete={canManage ? handleDelete : undefined} />
                    ))}
                </div>
            )}

            <IntegrationFormModal
                show={showModal}
                onHide={() => setShowModal(false)}
                capability={capability}
                integration={editingRow}
                clusters={clusters}
                onSaved={onRefresh}
            />
        </div>
    );
}

/* ─── Exported Panel Components ──────────────────────────────────────── */

export function LogProviderPanel({ integrations, onRefresh }) {
    return <ProviderPanel capability="logs" integrations={integrations} onRefresh={onRefresh} />;
}
export function MetricProviderPanel({ integrations, onRefresh }) {
    return <ProviderPanel capability="metrics" integrations={integrations} onRefresh={onRefresh} />;
}
