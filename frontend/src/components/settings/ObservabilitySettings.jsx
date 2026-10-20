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

import React, { useState, useEffect, useCallback } from "react";
import { Modal, Button, Form, Badge } from "react-bootstrap";
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

const TIER_META = {
    primary:  { label: "Primary",  bg: "#e3f2fd", fg: "#1565c0" },
    fallback: { label: "Fallback", bg: "#fff3e0", fg: "#ef6c00" },
    tertiary: { label: "Tertiary", bg: "#f5f5f5", fg: "#616161" },
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
    const label = cap === "logs" ? "Logs" : "Metrics";
    const bg = cap === "logs" ? "#e8f5e9" : "#e3f2fd";
    const fg = cap === "logs" ? "#2e7d32" : "#1565c0";
    return (
        <span style={{
            display: "inline-block", fontSize: 11, fontWeight: 600,
            padding: "2px 8px", borderRadius: 10, backgroundColor: bg,
            color: fg, marginRight: 4,
        }}>{label}</span>
    );
}

function StatusBadge({ status }) {
    if (status === true)  return <span style={{ color: "#2e7d32", fontSize: 12 }}><FaCheck /> Healthy</span>;
    if (status === false) return <span style={{ color: "#c62828", fontSize: 12 }}><FaTimes /> Unhealthy</span>;
    return <span style={{ color: "#999", fontSize: 12 }}>—</span>;
}

function TierBadge({ tier }) {
    const meta = TIER_META[tier] || TIER_META.primary;
    return (
        <span style={{
            display: "inline-block", fontSize: 10, fontWeight: 700,
            letterSpacing: 0.4, textTransform: "uppercase",
            padding: "2px 8px", borderRadius: 4,
            backgroundColor: meta.bg, color: meta.fg,
        }}>{meta.label}</span>
    );
}

function ScopePills({ integration, clusterName }) {
    const scope = integration.scope || {};
    const items = [];
    if (scope.environment) items.push({ icon: <FaTag size={9} />, key: "env", val: scope.environment, bg: "#e3f2fd", fg: "#1565c0" });
    if (clusterName)       items.push({ icon: <FaServer size={9} />, key: "cluster", val: clusterName, bg: "#e0f7fa", fg: "#00838f" });
    if (scope.region)      items.push({ icon: <FaGlobe size={9} />, key: "region", val: scope.region, bg: "#eeeeee", fg: "#424242" });
    if (scope.namespace)   items.push({ icon: <FaCube size={9} />, key: "ns", val: scope.namespace, bg: "#fff8e1", fg: "#ff8f00" });
    if (items.length === 0) {
        return <span style={{ color: "#999", fontSize: 12, fontStyle: "italic" }}>unscoped — serves any</span>;
    }
    return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {items.map((p) => (
                <span key={p.key} style={{
                    display: "inline-flex", alignItems: "center", gap: 4,
                    fontSize: 11, fontWeight: 500, padding: "2px 8px",
                    borderRadius: 10, backgroundColor: p.bg, color: p.fg,
                }}>{p.icon}{p.key}={p.val}</span>
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
                <div style={{ marginBottom: 16 }}>
                    <label style={{ fontSize: 12, fontWeight: 600, color: "#555", display: "block", marginBottom: 8 }}>
                        Provider
                    </label>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(120px, 1fr))", gap: 8 }}>
                        {filteredProviders.map(([code, meta]) => {
                            const Icon = meta.icon;
                            const isSelected = code === selectedProvider;
                            const disabled = isEdit && code !== integration.provider;
                            return (
                                <div key={code}
                                    onClick={() => !disabled && handleSelectProvider(code)}
                                    style={{
                                        display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
                                        padding: "12px 8px", borderRadius: 8,
                                        border: isSelected ? `2px solid ${meta.color}` : "2px solid #e0e0e0",
                                        backgroundColor: isSelected ? `${meta.color}10` : "#fff",
                                        cursor: disabled ? "not-allowed" : "pointer",
                                        opacity: disabled ? 0.35 : 1,
                                    }}>
                                    <Icon size={22} color={meta.color} />
                                    <span style={{ fontSize: 11, fontWeight: 600 }}>{meta.name}</span>
                                </div>
                            );
                        })}
                    </div>
                </div>

                {providerMeta && (
                    <>
                        {/* Priority tier + cluster + scope */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                            <Form.Group>
                                <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>Priority tier</Form.Label>
                                <Form.Select value={tier} onChange={(e) => setTier(e.target.value)} size="sm">
                                    <option value="primary">Primary — tried first</option>
                                    <option value="fallback">Fallback — on primary error</option>
                                    <option value="tertiary">Tertiary — last resort</option>
                                </Form.Select>
                            </Form.Group>
                            {clusters.length > 0 && (
                                <Form.Group>
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

                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16, padding: 12, background: "#fafafa", borderRadius: 6 }}>
                            <Form.Group>
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "#666" }}>
                                    <FaTag size={10} style={{ marginRight: 4 }} />Environment
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="production"
                                    value={scope.environment}
                                    onChange={(e) => setScope({ ...scope, environment: e.target.value })} />
                            </Form.Group>
                            <Form.Group>
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "#666" }}>
                                    <FaGlobe size={10} style={{ marginRight: 4 }} />Region
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="us-east-1"
                                    value={scope.region}
                                    onChange={(e) => setScope({ ...scope, region: e.target.value })} />
                            </Form.Group>
                            <Form.Group>
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "#666" }}>
                                    <FaCube size={10} style={{ marginRight: 4 }} />Namespace
                                    {!clusterId && <span style={{ marginLeft: 4, fontSize: 9, color: "#999" }}>(needs cluster)</span>}
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="payments"
                                    value={scope.namespace}
                                    disabled={!clusterId}
                                    onChange={(e) => setScope({ ...scope, namespace: e.target.value })} />
                            </Form.Group>
                        </div>

                        {/* Capabilities toggles for dual-cap providers */}
                        {providerMeta.capabilities.length > 1 && (
                            <div style={{ marginBottom: 14, padding: 10, backgroundColor: "#f5f5f5", borderRadius: 6 }}>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "#555", marginRight: 10 }}>Capabilities:</span>
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
                                <Form.Group key={field.name} style={{ marginBottom: 12 }}>
                                    <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>
                                        {field.label} {field.required && <span style={{ color: "#c62828" }}>*</span>}
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
        <div style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "12px 14px", borderRadius: 8, border: "1px solid #e0e0e0",
            backgroundColor: "#fff", marginBottom: 8,
        }}>
            <Icon size={22} color={meta?.color || "#666"} style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 13 }}>
                        {integration.display_name || meta?.name || integration.provider}
                    </span>
                    <TierBadge tier={integration.priority_tier} />
                    {integration.capabilities?.map((c) => <CapBadge key={c} cap={c} />)}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "#666" }}>
                    <ScopePills integration={integration} clusterName={clusterName} />
                </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                <StatusBadge status={integration.last_health_status} />
                {onEdit && (
                    <Button variant="light" size="sm" onClick={() => onEdit(integration)} title="Edit">
                        <FaEdit size={12} />
                    </Button>
                )}
                {onDelete && (
                    <Button variant="outline-danger" size="sm" onClick={() => onDelete(integration)} title="Delete">
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                <div>
                    <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
                        {capability === "logs" ? "Log Providers" : "Metric Providers"}
                        <Badge bg="secondary" style={{ marginLeft: 8 }}>{rows.length}</Badge>
                    </h4>
                    <div style={{ fontSize: 11, color: "#888", marginTop: 2 }}>
                        Ordered by priority tier. The batch pipeline tries primary first, then fallback, then tertiary.
                    </div>
                </div>
                {canManage && (
                <Button variant="primary" size="sm" onClick={openCreate}>
                    <FaPlus size={12} /> Add {capability === "logs" ? "log" : "metric"} provider
                </Button>
                )}
            </div>

            {rows.length === 0 ? (
                <div className="settings-card" style={{ textAlign: "center", color: "#888", padding: 40 }}>
                    <FaPlug size={28} style={{ marginBottom: 8, opacity: 0.4 }} />
                    <p style={{ margin: 0, fontSize: 14 }}>
                        No {capability === "logs" ? "log" : "metric"} providers configured yet.
                    </p>
                    <p style={{ margin: "4px 0 0", fontSize: 12 }}>
                        Using system default until you add one.
                    </p>
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

/* ─── Full Standalone Component (default export) ─────────────────────── */

export default function ObservabilitySettings() {
    const [integrations, setIntegrations] = useState([]);
    const [activeTab, setActiveTab] = useState("logs");
    const [loading, setLoading] = useState(true);

    const fetchData = useCallback(async () => {
        try {
            const data = await ObservabilityService.getAll();
            setIntegrations(Array.isArray(data) ? data : data.results || []);
        } catch (err) {
            console.error("Failed to load integrations:", err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);

    if (loading) {
        return (
            <div style={{ textAlign: "center", padding: 60 }}>
                <FaSpinner className="spin" size={24} />
            </div>
        );
    }

    const tabs = [
        { key: "logs", label: "Log Providers" },
        { key: "metrics", label: "Metric Providers" },
    ];

    return (
        <div>
            <div style={{ display: "flex", gap: 0, borderBottom: "2px solid #e0e0e0", marginBottom: 20 }}>
                {tabs.map((t) => (
                    <button key={t.key} onClick={() => setActiveTab(t.key)}
                        style={{
                            padding: "10px 20px", fontSize: 13, fontWeight: 600, border: "none",
                            borderBottom: activeTab === t.key ? "2px solid var(--primary-color, #e8734a)" : "2px solid transparent",
                            color: activeTab === t.key ? "var(--primary-color, #e8734a)" : "#666",
                            backgroundColor: "transparent", cursor: "pointer", marginBottom: -2,
                        }}>{t.label}</button>
                ))}
            </div>

            {activeTab === "logs"    && <LogProviderPanel    integrations={integrations} onRefresh={fetchData} />}
            {activeTab === "metrics" && <MetricProviderPanel integrations={integrations} onRefresh={fetchData} />}
        </div>
    );
}
