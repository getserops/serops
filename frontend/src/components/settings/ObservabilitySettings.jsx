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
    SiOpensearch,
    SiSplunk,
    SiGooglecloud,
    SiJaeger,
} from "react-icons/si";
import {
    FaChartLine, FaCheck, FaTimes, FaSpinner, FaPlug, FaTrash,
    FaServer, FaPlus, FaEdit, FaTag, FaGlobe, FaCube, FaMicrosoft, FaProjectDiagram,
    // Simple Icons dropped the AWS logo (react-icons 5.6+ ships without SiAmazonwebservices).
    FaAws,
} from "react-icons/fa";
import { useTranslation } from "react-i18next";
import { describeRequestError } from "../../utils/apiError";
import ObservabilityService from "../../services/observability.service";
import ClusterService from "../../services/cluster.service";
import ChoiceGroup from "./ChoiceGroup";
import IntegrationsSectionHeader from "./IntegrationsSectionHeader";
import { usePermissions } from "../../utils/permissions";
import { isDemoUser } from "../../utils/demo";
import { liveTested, liveTestedDetail } from "../../utils/integrationMaturity";

/* ─── Provider Metadata ──────────────────────────────────────────────── */

const PROVIDERS = {
    elasticsearch: {
        name: "Elasticsearch", icon: SiElasticsearch, color: "#FEC514",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "observabilitySettings.field.hostUrl", type: "url", placeholder: "http://elasticsearch:9200", required: true },
            { name: "username", label: "observabilitySettings.field.username", placeholder: "elastic" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.index_pattern", label: "observabilitySettings.field.indexPattern", placeholder: "logs-*, filebeat-*",
              help: "observabilitySettings.field.indexPatternHelp" },
            { name: "extra_config.verify_certs", label: "observabilitySettings.field.verifyTls", type: "checkbox", defaultChecked: true },
        ],
    },
    opensearch: {
        name: "OpenSearch", icon: SiOpensearch, color: "#005EB8",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "observabilitySettings.field.hostUrl", type: "url", placeholder: "https://opensearch:9200", required: true },
            { name: "username", label: "observabilitySettings.field.username" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.index_pattern", label: "observabilitySettings.field.indexPattern", placeholder: "logs-*, filebeat-*",
              help: "observabilitySettings.field.indexPatternHelp" },
            { name: "extra_config.verify_certs", label: "observabilitySettings.field.verifyTls", type: "checkbox", defaultChecked: true },
        ],
    },
    loki: {
        name: "Grafana Loki", icon: SiGrafana, color: "#F46800",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "observabilitySettings.field.lokiUrl", type: "url", placeholder: "http://loki:3100", required: true },
            { name: "extra_config.tenant_id", label: "observabilitySettings.field.tenantId", placeholder: "default" },
        ],
    },
    // Splunk, Google Cloud and Azure Monitor were only in the onboarding
    // wizard (journey suite, B14).
    splunk: {
        name: "Splunk", icon: SiSplunk, color: "#65A637",
        capabilities: ["logs"],
        fields: [
            { name: "host", label: "observabilitySettings.field.splunkUrl", type: "url", placeholder: "https://splunk:8089", required: true },
            { name: "password", label: "observabilitySettings.field.authToken", type: "password", placeholder: "Splunk → Settings → Tokens", required: true },
            { name: "extra_config.index", label: "observabilitySettings.field.index", placeholder: "main" },
            // Self-signed management certificates are common on Splunk Enterprise.
            { name: "extra_config.verify_ssl", label: "observabilitySettings.field.verifyTls", type: "checkbox", defaultChecked: true },
        ],
    },
    prometheus: {
        name: "Prometheus", icon: SiPrometheus, color: "#E6522C",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "observabilitySettings.field.prometheusUrl", type: "url", placeholder: "http://prometheus:9090", required: true },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password", placeholderKey: "observabilitySettings.field.bearerGrafanaThanos" },
        ],
    },
    victoriametrics: {
        name: "VictoriaMetrics", icon: FaChartLine, color: "#621773",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "observabilitySettings.field.vmUrl", type: "url", placeholder: "http://victoria:8428", required: true },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password", placeholderKey: "observabilitySettings.field.bearerVmCloud" },
        ],
    },
    mimir: {
        name: "Grafana Mimir", icon: SiGrafana, color: "#FF5733",
        capabilities: ["metrics"],
        fields: [
            { name: "host", label: "observabilitySettings.field.mimirUrl", type: "url", placeholder: "http://mimir:9009", required: true },
            { name: "extra_config.tenant_id", label: "observabilitySettings.field.tenantId", placeholder: "default" },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password", placeholderKey: "observabilitySettings.field.bearerGrafanaCloud" },
        ],
    },
    datadog: {
        name: "Datadog", icon: SiDatadog, color: "#632CA6",
        capabilities: ["logs", "metrics", "traces"],
        fields: [
            { name: "host", label: "observabilitySettings.field.datadogSite", placeholder: "datadoghq.com", required: true,
              help: "observabilitySettings.field.datadogSiteHelp" },
            { name: "extra_config.api_key", label: "observabilitySettings.field.apiKey", type: "password", required: true },
            // Searching logs and querying metrics need it, not only the API key.
            { name: "extra_config.app_key", label: "observabilitySettings.field.appKey", type: "password", required: true,
              help: "observabilitySettings.field.appKeyHelp" },
        ],
    },
    cloudwatch: {
        name: "AWS CloudWatch", icon: FaAws, color: "#FF9900",
        capabilities: ["logs", "metrics"],
        fields: [
            { name: "extra_config.aws_region", label: "observabilitySettings.field.awsRegion", placeholder: "us-east-1", required: true },
            { name: "username", label: "observabilitySettings.field.accessKeyId", required: true },
            { name: "password", label: "observabilitySettings.field.secretAccessKey", type: "password", required: true },
            { name: "extra_config.log_groups", label: "observabilitySettings.field.logGroups", placeholder: "/ecs/shop-api, /aws/lambda/checkout",
              help: "observabilitySettings.field.logGroupsHelp" },
        ],
    },
    gcp: {
        name: "Google Cloud", icon: SiGooglecloud, color: "#4285F4",
        capabilities: ["logs", "metrics"],
        fields: [
            { name: "extra_config.project_id", label: "observabilitySettings.field.projectId", placeholder: "my-project", required: true },
            { name: "password", label: "observabilitySettings.field.gcpKey", type: "password", placeholderKey: "observabilitySettings.field.gcpKeyPlaceholder", required: true },
        ],
    },
    azure: {
        name: "Azure Monitor", icon: FaMicrosoft, color: "#0078D4",
        capabilities: ["logs", "metrics"],
        fields: [
            { name: "extra_config.tenant_id", label: "observabilitySettings.field.tenantId", required: true },
            { name: "extra_config.client_id", label: "observabilitySettings.field.clientId", required: true },
            { name: "password", label: "observabilitySettings.field.clientSecret", type: "password", required: true },
            { name: "extra_config.workspace_id", label: "observabilitySettings.field.workspaceId", placeholderKey: "observabilitySettings.field.workspacePlaceholder" },
            { name: "extra_config.default_resource_uri", label: "observabilitySettings.field.resourceUri", placeholderKey: "observabilitySettings.field.resourcePlaceholder" },
        ],
    },
    // Trace stores SerOps pulls from (traces.md). OTLP sent to SerOps
    // needs no provider. There was no way to add these in Settings (B16).
    jaeger: {
        name: "Jaeger", icon: SiJaeger, color: "#66CFE3",
        capabilities: ["traces"],
        fields: [
            { name: "host", label: "observabilitySettings.field.jaegerUrl", type: "url", placeholder: "http://jaeger-query:16686", required: true },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password" },
        ],
    },
    zipkin: {
        name: "Zipkin", icon: FaProjectDiagram, color: "#FE7139",
        capabilities: ["traces"],
        fields: [
            { name: "host", label: "observabilitySettings.field.zipkinUrl", type: "url", placeholder: "http://zipkin:9411", required: true },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password" },
        ],
    },
    tempo: {
        name: "Grafana Tempo", icon: SiGrafana, color: "#F46800",
        capabilities: ["traces"],
        fields: [
            { name: "host", label: "observabilitySettings.field.tempoUrl", type: "url", placeholder: "http://tempo:3200", required: true },
            { name: "extra_config.tenant_id", label: "observabilitySettings.field.tenantId", placeholderKey: "observabilitySettings.field.optional" },
            { name: "username", label: "observabilitySettings.field.username", placeholderKey: "observabilitySettings.field.optional" },
            { name: "password", label: "observabilitySettings.field.password", type: "password" },
            { name: "extra_config.bearer_token", label: "observabilitySettings.field.bearerToken", type: "password" },
        ],
    },
};

// Chip tones from the design system (styles/design.css · Badges).
const TIER_META = {
    primary:  { label: "observabilitySettings.tier.primary",  tone: "ds-chip-brand" },
    fallback: { label: "observabilitySettings.tier.fallback", tone: "ds-chip-warn" },
    tertiary: { label: "observabilitySettings.tier.tertiary", tone: "ds-chip-neutral" },
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
    const { t } = useTranslation();
    const tone = { logs: "ds-chip-ok", metrics: "ds-chip-info", traces: "ds-chip-brand" }[cap] || "ds-chip-neutral";
    return <span className={`ds-chip ${tone}`}>{t(`observabilitySettings.cap.${cap}`, cap.charAt(0).toUpperCase() + cap.slice(1))}</span>;
}

function StatusBadge({ status }) {
    const { t } = useTranslation();
    if (status === true)  return <span className="obs-status" style={{ color: "var(--tone-green-text)" }}><FaCheck /> {t("observabilitySettings.healthy")}</span>;
    if (status === false) return <span className="obs-status" style={{ color: "var(--tone-red-text)" }}><FaTimes /> {t("observabilitySettings.unhealthy")}</span>;
    return <span className="obs-status" style={{ color: "var(--text-tertiary)" }}>—</span>;
}

function TierBadge({ tier }) {
    const { t } = useTranslation();
    const meta = TIER_META[tier] || TIER_META.primary;
    return <span className={`ds-chip ${meta.tone}`}>{t(meta.label)}</span>;
}

function ScopePills({ integration, clusterName }) {
    const { t } = useTranslation();
    const scope = integration.scope || {};
    const items = [];
    if (scope.environment) items.push({ icon: <FaTag size={9} />, key: "env", val: scope.environment, tone: "ds-chip-brand" });
    if (clusterName)       items.push({ icon: <FaServer size={9} />, key: "cluster", val: clusterName, tone: "ds-chip-info" });
    if (scope.region)      items.push({ icon: <FaGlobe size={9} />, key: "region", val: scope.region, tone: "ds-chip-neutral" });
    if (scope.namespace)   items.push({ icon: <FaCube size={9} />, key: "ns", val: scope.namespace, tone: "ds-chip-warn" });
    if (items.length === 0) {
        return <span className="obs-unscoped">{t("observabilitySettings.unscoped")}</span>;
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
    const { t } = useTranslation();
    const isEdit = !!integration;
    const [selectedProvider, setSelectedProvider] = useState(null);
    const [form, setForm] = useState({});
    const [enabledCaps, setEnabledCaps] = useState([capability]);
    const [clusterId, setClusterId] = useState(null);
    const [tier, setTier] = useState("primary");
    const [topology, setTopology] = useState("vm");
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
            setTopology(integration.topology_mode || "vm");
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
            setTopology("vm");
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
            toast.error(t("observabilitySettings.namespaceNeedsCluster"));
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
                topology_mode: topology,
                scope: {
                    environment: scope.environment || "",
                    region: scope.region || "",
                    namespace: scope.namespace || "",
                },
            };
            if (form.password) payload.password = form.password;

            if (isEdit) {
                await ObservabilityService.update(integration.id, payload);
                toast.success(t("globalIntegrations.updated"));
            } else {
                await ObservabilityService.create(payload);
                toast.success(t("globalIntegrations.created"));
            }
            onSaved();
            onHide();
        } catch (err) {
            // Any field's reason (a duplicate provider, a second primary):
            // only a few were read, so some failures said nothing (B15).
            toast.error(describeRequestError(err, t("observabilitySettings.saveFailed")));
        } finally {
            setSaving(false);
        }
    }

    async function handleTest() {
        if (!isEdit) {
            toast.info(t("observabilitySettings.saveFirst"));
            return;
        }
        setTesting(true);
        try {
            const result = await ObservabilityService.healthCheck(integration.id);
            const allOk = result.integrations?.every((r) => r.healthy);
            if (allOk) toast.success(t("observabilitySettings.connectionHealthy"));
            else {
                const failing = result.integrations?.filter((r) => !r.healthy);
                toast.error(t("observabilitySettings.healthCheckFailed", { messages: failing?.map((r) => r.message).join(", ") }));
            }
            onSaved();
        } catch {
            toast.error(t("observabilitySettings.connectionTestFailed"));
        } finally {
            setTesting(false);
        }
    }

    return (
        <Modal show={show} onHide={onHide} size="lg" centered>
            <Modal.Header closeButton>
                <Modal.Title>
                    {isEdit ? t("observabilitySettings.editTitle", { name: PROVIDERS[integration.provider]?.name || t("observabilitySettings.integrationFallbackName") })
                            : t(`observabilitySettings.newTitle.${capability}`)}
                </Modal.Title>
            </Modal.Header>
            <Modal.Body>
                {/* Provider grid — disabled when editing (provider is immutable) */}
                <ChoiceGroup
                    variant="cards"
                    className="mb-3"
                    label={t("globalIntegrations.provider")}
                    value={selectedProvider}
                    onChange={handleSelectProvider}
                    options={filteredProviders.map(([code, meta]) => ({
                        value: code,
                        // The provider can't change once an integration exists.
                        disabled: isEdit && code !== integration.provider,
                        label: <span className="d-inline-flex align-items-center gap-2">{React.createElement(meta.icon, { size: 18, color: meta.color, "aria-hidden": true })}{meta.name}</span>,
                        description: liveTestedDetail(code) || undefined,
                        badge: liveTested(code) && <span className="badge ds-chip ds-chip-ok" title={t("observabilitySettings.liveTestedTitle", { detail: liveTestedDetail(code) })}>{t("observabilitySettings.liveTested")}</span>,
                    }))}
                />

                {providerMeta && (
                    <>
                        {/* Priority tier + cluster + scope */}
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                            <Form.Group controlId="obs-tier">
                                <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>{t("observabilitySettings.priorityTier")}</Form.Label>
                                <Form.Select value={tier} onChange={(e) => setTier(e.target.value)} size="sm">
                                    <option value="primary">{t("observabilitySettings.tierOption.primary")}</option>
                                    <option value="fallback">{t("observabilitySettings.tierOption.fallback")}</option>
                                    <option value="tertiary">{t("observabilitySettings.tierOption.tertiary")}</option>
                                </Form.Select>
                            </Form.Group>
                            {clusters.length > 0 && (
                                <Form.Group controlId="obs-cluster">
                                    <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>
                                        <FaServer style={{ marginRight: 4 }} />{t("observabilitySettings.clusterScope")}
                                    </Form.Label>
                                    <Form.Select
                                        value={clusterId ?? ""}
                                        onChange={(e) => setClusterId(e.target.value ? parseInt(e.target.value, 10) : null)}
                                        size="sm"
                                    >
                                        <option value="">{t("observabilitySettings.unscopedAnyCluster")}</option>
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
                                    <FaTag size={10} style={{ marginRight: 4 }} />{t("observabilitySettings.environment")}
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="production"
                                    value={scope.environment}
                                    onChange={(e) => setScope({ ...scope, environment: e.target.value })} />
                            </Form.Group>
                            <Form.Group controlId="obs-region">
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)" }}>
                                    <FaGlobe size={10} style={{ marginRight: 4 }} />{t("observabilitySettings.region")}
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="us-east-1"
                                    value={scope.region}
                                    onChange={(e) => setScope({ ...scope, region: e.target.value })} />
                            </Form.Group>
                            <Form.Group controlId="obs-namespace">
                                <Form.Label style={{ fontSize: 11, fontWeight: 600, color: "var(--text-secondary)" }}>
                                    <FaCube size={10} style={{ marginRight: 4 }} />{t("observabilitySettings.namespace")}
                                    {!clusterId && <>{" "}<span style={{ fontSize: 9, color: "var(--text-tertiary)" }}>{t("observabilitySettings.needsCluster")}</span></>}
                                </Form.Label>
                                <Form.Control size="sm" type="text" placeholder="payments"
                                    value={scope.namespace}
                                    disabled={!clusterId}
                                    onChange={(e) => setScope({ ...scope, namespace: e.target.value })} />
                            </Form.Group>
                        </div>

                        {/* How metric queries group series (docs: Topology Mode). It
                            was API-only although the docs point here (B3). */}
                        {enabledCaps.includes("metrics") && (
                            <Form.Group controlId="obs-topology" style={{ marginBottom: 12 }}>
                                <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>{t("observabilitySettings.topologyMode")}</Form.Label>
                                <Form.Select value={topology} onChange={(e) => setTopology(e.target.value)} size="sm">
                                    <option value="vm">{t("observabilitySettings.topologyVm")}</option>
                                    <option value="kubernetes">{t("observabilitySettings.topologyKubernetes")}</option>
                                </Form.Select>
                            </Form.Group>
                        )}

                        {/* Capabilities toggles for dual-cap providers */}
                        {providerMeta.capabilities.length > 1 && (
                            <div style={{ marginBottom: 14, padding: 10, backgroundColor: "var(--bg-sunken)", borderRadius: 6 }}>
                                <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", marginRight: 10 }}>{t("observabilitySettings.capabilities")}</span>
                                {providerMeta.capabilities.map((cap) => (
                                    <label key={cap} style={{ marginRight: 14, cursor: "pointer", fontSize: 13 }}>
                                        <input type="checkbox" checked={enabledCaps.includes(cap)}
                                            onChange={() => toggleCap(cap)} style={{ marginRight: 4 }} />
                                        {t(`observabilitySettings.capProvider.${cap}`)}
                                    </label>
                                ))}
                            </div>
                        )}

                        {/* Provider-specific connection fields */}
                        {providerMeta.fields.map((field) => {
                            if (field.type === "checkbox") {
                                const value = getNestedValue(form, field.name);
                                return (
                                    <Form.Check key={field.name} id={`obs-${field.name}`} type="checkbox" style={{ marginBottom: 12 }}
                                        label={t(field.label)}
                                        checked={value === "" || value === undefined ? !!field.defaultChecked : !!value}
                                        onChange={(e) => handleFieldChange(field.name, e.target.checked)} />
                                );
                            }
                            const isSecret = field.type === "password";
                            const hasStoredValue = isSecret && isEdit && (
                                field.name === "password"
                                    ? integration?.has_password
                                    : (integration?.secret_fields_set || []).includes(field.name.replace("extra_config.", ""))
                            );
                            const placeholder = hasStoredValue && !getNestedValue(form, field.name)
                                ? t("observabilitySettings.keepSecret")
                                : (field.placeholderKey ? t(field.placeholderKey) : (field.placeholder || ""));
                            return (
                                <Form.Group key={field.name} controlId={`obs-${field.name}`} style={{ marginBottom: 12 }}>
                                    <Form.Label style={{ fontSize: 12, fontWeight: 600 }}>
                                        {t(field.label)} {field.required && <span style={{ color: "var(--tone-red-text)" }}>*</span>}
                                    </Form.Label>
                                    <Form.Control type={field.type || "text"} size="sm"
                                        placeholder={placeholder}
                                        value={getNestedValue(form, field.name) || ""}
                                        onChange={(e) => handleFieldChange(field.name, e.target.value)} />
                                    {field.help && <Form.Text muted>{t(field.help)}</Form.Text>}
                                </Form.Group>
                            );
                        })}
                    </>
                )}
            </Modal.Body>
            <Modal.Footer>
                {isEdit && (
                    <Button variant="outline-primary" size="sm" onClick={handleTest} disabled={testing} className="me-auto">
                        {testing ? <><FaSpinner className="spin" /> {t("observabilitySettings.testing")}</> : <><FaPlug /> {t("observabilitySettings.test")}</>}
                    </Button>
                )}
                <Button variant="secondary" onClick={onHide} size="sm">{t("common.cancel")}</Button>
                <Button variant="primary" onClick={handleSave} disabled={saving || !selectedProvider} size="sm">
                    {saving ? <><FaSpinner className="spin" /> {t("observabilitySettings.saving")}</> : (isEdit ? t("observabilitySettings.update") : t("observabilitySettings.create"))}
                </Button>
            </Modal.Footer>
        </Modal>
    );
}

/* ─── Integration Row + List ─────────────────────────────────────────── */

function IntegrationRow({ integration, clusters, onEdit, onDelete }) {
    const { t } = useTranslation();
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
                    <Button variant="outline-secondary" size="sm" onClick={() => onEdit(integration)} title={t("common.edit")} aria-label={t("common.edit")}>
                        <FaEdit size={12} />
                    </Button>
                )}
                {onDelete && (
                    <Button variant="outline-danger" size="sm" onClick={() => onDelete(integration)} title={t("common.delete")} aria-label={t("common.delete")}>
                        <FaTrash size={12} />
                    </Button>
                )}
            </div>
        </div>
    );
}

function ProviderPanel({ capability, integrations, onRefresh }) {
    const { t } = useTranslation();
    // Sources hold credentials: only admins add, edit or delete them (the API enforces it).
    // The demo lists the stores its analyses read, with nothing to add, edit or delete.
    const canManage = usePermissions()("integration.manage") && !isDemoUser();
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
        if (!window.confirm(t("observabilitySettings.confirmRemove", { tier: row.priority_tier, label }))) return;
        try {
            await ObservabilityService.delete(row.id);
            toast.success(t("observabilitySettings.removed"));
            onRefresh();
        } catch {
            toast.error(t("observabilitySettings.removeFailed"));
        }
    }

    function openCreate() { setEditingRow(null); setShowModal(true); }
    function openEdit(row) { setEditingRow(row); setShowModal(true); }

    return (
        <div>
            <IntegrationsSectionHeader
                title={t(`globalIntegrations.tabs.${capability}`)}
                count={rows.length}
                description={capability === "traces"
                    ? t("observabilitySettings.descTraces")
                    : t("observabilitySettings.descTiers")}
                action={canManage && (
                    <Button variant="primary" onClick={openCreate}>
                        <FaPlus aria-hidden="true" /> {t(`observabilitySettings.add.${capability}`)}
                    </Button>
                )}
            />

            {rows.length === 0 ? (
                <div className="text-center py-5 text-muted">
                    <FaPlug size={40} className="mb-2 opacity-50" />
                    <p>{t(`observabilitySettings.empty.${capability}`)}</p>
                    <p className="small">{capability === "traces" ? t("observabilitySettings.emptyTracesNote") : t("observabilitySettings.emptyDefaultNote")}</p>
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
export function TraceProviderPanel({ integrations, onRefresh }) {
    return <ProviderPanel capability="traces" integrations={integrations} onRefresh={onRefresh} />;
}
