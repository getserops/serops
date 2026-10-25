/**
 * Unified Integrations Settings — 4 Tabs
 *
 * Tabs: Source Control | CI/CD | Log Providers | Metric Providers
 *
 * Source Control & CI/CD: existing ProviderIntegration CRUD (SCM/CI/CD).
 * Log / Metric Providers: ObservabilityIntegration panels.
 */

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
    Form,
    Button,
    Modal,
    Badge,
    Spinner,
    Alert,
    Card,
    Row,
    Col,
    Dropdown,
    OverlayTrigger,
    Tooltip,
    Collapse,
    InputGroup,
} from "react-bootstrap";
import {
    FaTrash,
    FaEdit,
    FaPlus,
    FaCheck,
    FaTimes,
    FaSync,
    FaGitlab,
    FaGithub,
    FaBitbucket,
    FaCloud,
    FaLock,
    FaPlug,
    FaExternalLinkAlt,
    FaCogs,
    FaInfoCircle,
    FaEllipsisV,
    FaClock,
    FaLink,
    FaChevronDown,
    FaChevronUp,
    FaHistory,
    FaCheckCircle,
    FaExclamationCircle,
    FaFlask,
    FaCodeBranch,
    FaStream,
    FaChartLine,
    FaProjectDiagram,
} from "react-icons/fa";
import { SiArgo, SiFlux } from "react-icons/si";
import { useTranslation } from "react-i18next";
import PageHeader from './PageHeader';

import { IntegrationService } from "../services/integration.service";
import { toast } from "react-toastify";
import axios from "axios";
import ObservabilityService from "../services/observability.service";
import { LogProviderPanel, MetricProviderPanel, TraceProviderPanel } from "./settings/ObservabilitySettings";
import "./settings/SettingsLayout.css";
import ChoiceGroup from "./settings/ChoiceGroup";
import IntegrationsSectionHeader from "./settings/IntegrationsSectionHeader";
import { usePermissions } from "../utils/permissions";

// Provider configuration with specific credential fields and token URLs
const PROVIDERS = {
    gitlab: {
        name: "GitLab",
        icon: FaGitlab,
        color: "#FC6D26",
        caps: ["scm", "cicd", "deployments"],
        url: "https://gitlab.com",
        tokenUrl: (baseUrl) => `${baseUrl || 'https://gitlab.com'}/-/user_settings/personal_access_tokens`,
        tokenHelp: "Create with 'api' scope",
        fields: [
            { name: "base_url", label: "GitLab URL", type: "url", placeholder: "https://gitlab.com", required: false, help: "Leave blank for gitlab.com, or enter your self-hosted URL" },
            { name: "access_token", label: "Personal Access Token", type: "password", required: true, help: "Create at Settings → Access Tokens with api scope" },
        ],
    },
    github: {
        name: "GitHub",
        icon: FaGithub,
        color: "#181717",
        caps: ["scm", "cicd", "deployments"],
        url: "https://github.com",
        tokenUrl: () => "https://github.com/settings/tokens/new",
        tokenHelp: "Create with 'repo' scope",
        fields: [
            { name: "base_url", label: "GitHub URL", type: "url", placeholder: "https://github.com", required: false, help: "Leave blank for github.com, or enter GitHub Enterprise URL" },
            { name: "access_token", label: "Personal Access Token", type: "password", required: true, help: "Create at Settings → Developer Settings → Personal Access Tokens" },
        ],
    },
    azure_devops: {
        name: "Azure DevOps",
        icon: FaCloud,  // Using FaCloud for Azure DevOps
        color: "#0078D7",

        caps: ["scm", "cicd", "deployments"],
        url: "https://dev.azure.com",
        tokenUrl: (_, org) => `https://dev.azure.com/${org || '_'}/_usersSettings/tokens`,
        tokenHelp: "Create with 'Code (Read)' and 'Build (Read)' scopes",
        fields: [
            { name: "organization", label: "Organization", type: "text", required: true, placeholder: "my-org", help: "Your Azure DevOps organization name" },
            { name: "project", label: "Project (optional)", type: "text", required: false, placeholder: "my-project", help: "Leave blank to access all projects" },
            { name: "access_token", label: "Personal Access Token", type: "password", required: true, help: "Create at User Settings → Personal Access Tokens" },
        ],
    },
    bitbucket: {
        name: "Bitbucket",
        icon: FaBitbucket,  // Fixed: Use proper Bitbucket icon
        color: "#0052CC",
        caps: ["scm", "cicd"],
        url: "https://bitbucket.org",
        tokenUrl: () => "https://bitbucket.org/account/settings/app-passwords/",
        tokenHelp: "Create an App Password with repository read access",
        fields: [
            { name: "base_url", label: "Bitbucket URL", type: "url", placeholder: "https://bitbucket.org", required: false, help: "Leave blank for bitbucket.org, or enter Bitbucket Server URL" },
            { name: "username", label: "Username", type: "text", required: true, help: "Your Bitbucket username" },
            { name: "app_password", label: "App Password", type: "password", required: true, help: "Create at Personal Settings → App Passwords" },
        ],
    },
    jenkins: {
        name: "Jenkins",
        icon: FaCogs,
        color: "#D24939",
        caps: ["cicd", "deployments"],
        url: "",
        // Jenkins 2.x: API tokens live under the user's Security page.
        tokenUrl: (baseUrl, _org, creds) => `${baseUrl || ''}/user/${creds?.username || 'me'}/security`,
        tokenHelp: "Create an API Token at User → Configure",
        fields: [
            { name: "base_url", label: "Jenkins URL", type: "url", required: true, placeholder: "https://jenkins.company.com", help: "Your Jenkins server URL" },
            { name: "username", label: "Username", type: "text", required: true, help: "Jenkins user with API access" },
            { name: "api_token", label: "API Token", type: "password", required: true, help: "Create at User → Configure → API Token" },
        ],
    },
    // GitOps controllers send deployments to SerOps: no URL, no credentials.
    argocd: {
        name: "Argo CD",
        icon: SiArgo,
        color: "#EF7B4D",
        caps: ["deployments"],
        receiveOnly: true,
        url: "",
        fields: [],
    },
    flux: {
        name: "Flux",
        icon: SiFlux,
        color: "#5468FF",
        caps: ["deployments"],
        receiveOnly: true,
        url: "",
        fields: [],
    },
};

// The CI/CD tab lists build tools and the GitOps controllers that deploy.
const inCicdTab = (p) => p.caps.includes("cicd") || !!p.receiveOnly;

// URL validation regex
const URL_REGEX = /^https?:\/\/[a-zA-Z0-9][-a-zA-Z0-9]*(\.[a-zA-Z0-9][-a-zA-Z0-9]*)+[^\s]*$/;

// Helper to format relative time
const formatTimeAgo = (dateString) => {
    if (!dateString) return "Unknown";
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return date.toLocaleDateString();
};

// Extract hostname from URL for smart naming
const extractHostname = (url) => {
    try {
        const parsed = new URL(url);
        const host = parsed.hostname;
        // Remove common prefixes and TLDs
        const parts = host.split('.');
        if (parts.length >= 2) {
            // Return middle part (e.g., "mycompany" from "gitlab.mycompany.com")
            if (parts[0] === 'gitlab' || parts[0] === 'github' || parts[0] === 'bitbucket') {
                return parts[1];
            }
            return parts[0];
        }
        return host;
    } catch {
        return null;
    }
};

const TABS = [
    { key: "scm", icon: FaCodeBranch },
    { key: "cicd", icon: FaSync },
    { key: "logs", icon: FaStream },
    { key: "metrics", icon: FaChartLine },
    { key: "traces", icon: FaProjectDiagram },
];

const SettingsIntegrations = () => {
    const { t } = useTranslation();
    // The tab is in the URL (?tab=logs) so it can be linked to and survives a reload.
    const [searchParams, setSearchParams] = useSearchParams();
    const activeTab = TABS.some((tb) => tb.key === searchParams.get("tab")) ? searchParams.get("tab") : "scm";
    const setActiveTab = (key) => setSearchParams(key === "scm" ? {} : { tab: key }, { replace: true });
    const [integrations, setIntegrations] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    // Integrations hold provider credentials: only admins add, edit or
    // delete them (the API enforces this). Users can still sync.
    const canManage = usePermissions()("integration.manage");
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const [verifying, setVerifying] = useState({});
    const [selected, setSelected] = useState(null);
    const [saving, setSaving] = useState(false);
    const [showCapabilityMatrix, setShowCapabilityMatrix] = useState(false);
    const [integrationUsage, setIntegrationUsage] = useState({});

    // Observability integrations (log/metric providers)
    const [obsIntegrations, setObsIntegrations] = useState([]);
    const [obsLoading, setObsLoading] = useState(false);

    // Modal states
    const [testingConnection, setTestingConnection] = useState(false);
    const [connectionTestResult, setConnectionTestResult] = useState(null);
    const [urlValidation, setUrlValidation] = useState({});
    const [showConfigSection, setShowConfigSection] = useState(false);

    const [formData, setFormData] = useState({
        id: "",
        name: "",
        provider_type: "gitlab",
        credentials: {},
    });

    const fetchIntegrations = useCallback(async () => {
        try {
            setLoading(true);
            const data = await IntegrationService.getAll();
            setIntegrations(data || []);

            // Batch usage — single API call instead of N
            if (data && data.length > 0) {
                try {
                    const response = await axios.get(
                        `/api/providers/integrations/usage-summary/`,
                        { headers: { Authorization: `Token ${localStorage.getItem("token")}` } }
                    );
                    setIntegrationUsage(response.data || {});
                } catch {
                    setIntegrationUsage({});
                }
            }
        } catch (error) {
            toast.error(t("globalIntegrations.loadFailed", "Failed to load"));
        } finally {
            setLoading(false);
        }
    }, [t]);

    // The spinner is for the first load only: a refresh (after Test or Save)
    // replaced the panel with it and unmounted the open Edit dialog.
    const obsLoaded = React.useRef(false);
    const fetchObsIntegrations = useCallback(async () => {
        try {
            if (!obsLoaded.current) setObsLoading(true);
            const data = await ObservabilityService.getAll();
            setObsIntegrations(Array.isArray(data) ? data : data.results || []);
            obsLoaded.current = true;
        } catch (err) {
            console.error("Failed to load observability integrations:", err);
        } finally {
            setObsLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchIntegrations();
        fetchObsIntegrations();
    }, [fetchIntegrations, fetchObsIntegrations]);

    const handleVerify = async (integration) => {
        try {
            setVerifying((prev) => ({ ...prev, [integration.id]: true }));
            const response = await axios.post(
                `/api/providers/integrations/${integration.id}/verify/`,
                {},
                { headers: { Authorization: `Token ${localStorage.getItem("token")}` } }
            );
            if (response.data.success) {
                toast.success(t("globalIntegrations.verifySuccess", "Connection verified!"));
                fetchIntegrations();
            }
        } catch (err) {
            toast.error(err.response?.data?.message || t("globalIntegrations.verifyFailed", "Verification failed"));
            fetchIntegrations();
        } finally {
            setVerifying((prev) => ({ ...prev, [integration.id]: false }));
        }
    };

    const handleSync = async (integration) => {
        try {
            toast.info("Syncing...");
            await axios.post(
                `/api/providers/integrations/${integration.id}/sync/`,
                {},
                { headers: { Authorization: `Token ${localStorage.getItem("token")}` } }
            );
            toast.success("Sync completed!");
            fetchIntegrations();
        } catch (err) {
            toast.error("Sync failed");
        }
    };

    // Test connection before saving (new feature)
    const handleTestConnection = async () => {
        setTestingConnection(true);
        setConnectionTestResult(null);

        try {
            const provider = PROVIDERS[formData.provider_type];
            const testData = {
                provider_type: formData.provider_type,
                base_url: formData.credentials.base_url || provider.url,
                credentials: {},
            };

            // Build credentials
            provider.fields.forEach((field) => {
                const value = formData.credentials[field.name];
                if (value) {
                    if (field.name === "access_token" || field.name === "api_token" || field.name === "app_password") {
                        testData.access_token = value;
                    } else if (field.name !== "base_url") {
                        testData.credentials[field.name] = value;
                    }
                }
            });

            const response = await axios.post(
                `/api/providers/integrations/test/`,
                testData,
                { headers: { Authorization: `Token ${localStorage.getItem("token")}` } }
            );

            setConnectionTestResult({
                success: true,
                message: response.data.message || "Connection successful!",
                user_info: response.data.user_info
            });
        } catch (err) {
            setConnectionTestResult({
                success: false,
                message: err.response?.data?.message || err.response?.data?.error || "Connection failed"
            });
        } finally {
            setTestingConnection(false);
        }
    };

    // URL validation with visual feedback
    const validateUrl = (url, fieldName) => {
        if (!url) {
            setUrlValidation(prev => ({ ...prev, [fieldName]: null }));
            return;
        }

        const isValid = URL_REGEX.test(url);
        setUrlValidation(prev => ({
            ...prev,
            [fieldName]: {
                isValid,
                message: isValid ? "Valid URL" : "Invalid URL format"
            }
        }));
    };

    const handleInputChange = (e) => {
        const { name, value } = e.target;

        if (name === "name" || name === "provider_type") {
            setFormData((prev) => ({ ...prev, [name]: value }));
        } else {
            setFormData((prev) => ({
                ...prev,
                credentials: { ...prev.credentials, [name]: value },
            }));

            // Real-time URL validation
            if (name === "base_url") {
                validateUrl(value, name);

                // Smart placeholder: auto-suggest name based on URL
                if (value && !formData.name) {
                    const hostname = extractHostname(value);
                    if (hostname) {
                        const provider = PROVIDERS[formData.provider_type];
                        const suggestedName = `${hostname.charAt(0).toUpperCase() + hostname.slice(1)} ${provider.name}`;
                        setFormData(prev => ({ ...prev, name: suggestedName }));
                    }
                }
            }
        }

        // Clear test result when form changes
        setConnectionTestResult(null);
    };

    const selectProvider = (type) => {
        setFormData((prev) => ({
            ...prev,
            provider_type: type,
            name: "",  // Reset name for new provider
            credentials: { base_url: PROVIDERS[type]?.url || "" },
        }));
        setConnectionTestResult(null);
        setUrlValidation({});

        // Progressive disclosure: show config after selection
        setTimeout(() => setShowConfigSection(true), 100);
    };

    const openAdd = () => {
        setFormData({
            id: "",
            name: "",
            provider_type: "gitlab",
            credentials: { base_url: PROVIDERS.gitlab.url },
        });
        setIsEditing(false);
        setConnectionTestResult(null);
        setUrlValidation({});
        setShowConfigSection(false);
        setShowModal(true);
    };

    const openEdit = (int) => {
        setFormData({
            id: int.id,
            name: int.name,
            provider_type: int.provider_type,
            credentials: { base_url: int.base_url || "" },
        });
        setIsEditing(true);
        setConnectionTestResult(null);
        setShowConfigSection(true);
        setShowModal(true);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            setSaving(true);

            const provider = PROVIDERS[formData.provider_type];
            const data = {
                name: formData.name,
                provider_type: formData.provider_type,
                credentials: {},
            };

            provider.fields.forEach((field) => {
                const value = formData.credentials[field.name];
                if (value) {
                    if (field.name === "base_url") {
                        data.base_url = value;
                    } else if (field.name === "access_token" || field.name === "api_token" || field.name === "app_password") {
                        data.access_token = value;
                    } else {
                        data.credentials[field.name] = value;
                    }
                }
            });

            if (isEditing) {
                if (Object.keys(data.credentials).length === 0) delete data.credentials;
                if (!data.access_token) delete data.access_token;
                await IntegrationService.update(formData.id, data);
                toast.success(t("globalIntegrations.updated", "Updated"));
            } else {
                await IntegrationService.create(data);
                toast.success(t("globalIntegrations.created", "Created"));
            }
            setShowModal(false);
            fetchIntegrations();
        } catch (err) {
            toast.error(err.response?.data?.error || t("globalIntegrations.operationFailed", "Failed"));
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async () => {
        if (!selected) return;
        try {
            await IntegrationService.delete(selected.id);
            toast.success(t("globalIntegrations.deleted", "Deleted"));
            setShowDeleteModal(false);
            setSelected(null);
            fetchIntegrations();
        } catch (err) {
            toast.error(t("globalIntegrations.deleteFailed", "Delete failed"));
        }
    };

    const getProvider = (type) => PROVIDERS[type] || { name: type, icon: FaCloud, color: "var(--text-secondary)", caps: [], fields: [] };

    // Get token generation URL for current provider
    const getTokenUrl = useMemo(() => {
        const provider = PROVIDERS[formData.provider_type];
        if (!provider?.tokenUrl) return null;

        const baseUrl = formData.credentials.base_url || provider.url;
        const org = formData.credentials.organization;
        return provider.tokenUrl(baseUrl, org, formData.credentials);
    }, [formData.provider_type, formData.credentials]);

    // Render provider-specific fields with enhancements
    const renderProviderFields = () => {
        const provider = PROVIDERS[formData.provider_type];
        if (!provider?.fields) return null;
        if (provider.receiveOnly) {
            return (
                <p className="mb-0 small">
                    {provider.name} sends deployments to SerOps, so there is nothing to connect to.
                    Next, add a Deployment pipeline with this integration to the service it deploys:
                    that gives the webhook URL and secret to put in {provider.name}.
                </p>
            );
        }

        return provider.fields.map((field) => {
            const validation = urlValidation[field.name];
            const isUrlField = field.type === "url";

            return (
                <Form.Group className="mb-3" key={field.name} controlId={`integration-${field.name}`}>
                    <div className="d-flex align-items-center justify-content-between">
                        <Form.Label>
                            {field.label}
                            {!field.required && <span className="text-muted ms-1">(optional)</span>}
                        </Form.Label>
                        {/* Token generation link for password fields (outside the label) */}
                        {field.type === "password" && getTokenUrl && (
                            <a
                                href={getTokenUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="small text-decoration-none mb-2"
                            >
                                Generate token <FaExternalLinkAlt size={10} className="ms-1" aria-hidden="true" />
                            </a>
                        )}
                    </div>
                    <InputGroup>
                        <Form.Control
                            type={field.type}
                            name={field.name}
                            placeholder={isEditing && field.type === "password" ? "Leave blank to keep existing" : field.placeholder}
                            value={formData.credentials[field.name] || ""}
                            onChange={handleInputChange}
                            required={!isEditing && field.required}
                            isValid={isUrlField && validation?.isValid}
                            isInvalid={isUrlField && validation && !validation.isValid}
                            className={field.type === "password" ? "font-monospace" : ""}
                        />
                        {/* URL validation indicator */}
                        {isUrlField && validation && (
                            <InputGroup.Text className={validation.isValid ? "text-success bg-success-subtle" : "text-danger bg-danger-subtle"}>
                                {validation.isValid ? <FaCheckCircle /> : <FaExclamationCircle />}
                            </InputGroup.Text>
                        )}
                    </InputGroup>
                    {field.help && (
                        <Form.Text className="text-muted d-flex align-items-center gap-1">
                            {field.type === "password" ? <FaLock size={10} /> : <FaInfoCircle size={10} />}
                            {field.help}
                        </Form.Text>
                    )}
                </Form.Group>
            );
        });
    };

    // Capability matrix component (for modal)
    const CapabilityMatrix = () => (
        <div className="capability-matrix mt-3">
            <div
                className="d-flex align-items-center justify-content-between p-2 bg-light rounded cursor-pointer"
                onClick={() => setShowCapabilityMatrix(!showCapabilityMatrix)}
                style={{ cursor: "pointer" }}
            >
                <span className="d-flex align-items-center gap-2">
                    <FaInfoCircle className="text-muted" />
                    <small className="text-muted">Provider Capabilities</small>
                </span>
                {showCapabilityMatrix ? <FaChevronUp size={12} /> : <FaChevronDown size={12} />}
            </div>
            <Collapse in={showCapabilityMatrix}>
                <div className="mt-2">
                    <table className="table table-sm table-borderless mb-0" style={{ fontSize: "0.85rem" }}>
                        <thead>
                            <tr className="text-muted">
                                <th>Provider</th>
                                <th className="text-center">SCM</th>
                                <th className="text-center">CI/CD</th>
                                <th className="text-center">Deploy</th>
                            </tr>
                        </thead>
                        <tbody>
                            {Object.entries(PROVIDERS).map(([k, p]) => {
                                const I = p.icon;
                                return (
                                    <tr key={k} className={formData.provider_type === k ? "table-active" : ""}>
                                        <td><I size={14} style={{ color: p.color }} className="me-2" />{p.name}</td>
                                        <td className="text-center">{p.caps.includes("scm") ? <FaCheck className="text-success" size={12} /> : <FaTimes className="text-muted" size={12} />}</td>
                                        <td className="text-center">{p.caps.includes("cicd") ? <FaCheck className="text-success" size={12} /> : <FaTimes className="text-muted" size={12} />}</td>
                                        <td className="text-center">{p.caps.includes("deployments") ? <FaCheck className="text-success" size={12} /> : <FaTimes className="text-muted" size={12} />}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </Collapse>
        </div>
    );

    // Filter SCM integrations by tab
    const filteredIntegrations = useMemo(() => {
        if (activeTab === "scm") {
            return integrations.filter((int) => {
                const prov = PROVIDERS[int.provider_type];
                return prov && prov.caps.includes("scm");
            });
        }
        if (activeTab === "cicd") {
            return integrations.filter((int) => {
                const prov = PROVIDERS[int.provider_type];
                return prov && inCicdTab(prov);
            });
        }
        return [];
    }, [activeTab, integrations]);

    return (
        <div className="settings-section">
            {/* Header */}
            <PageHeader
                title={t("globalIntegrations.title", "Integrations")}
                subtitle={t("globalIntegrations.subtitle", "Connect your development tools and data sources")}
            />

            {/* Tab Bar */}
            <div className="nav nav-tabs mb-4" role="tablist" data-demo-allowed>
                {TABS.map((tab) => (
                    <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tab.key}
                        className={`nav-link ${activeTab === tab.key ? "active" : ""}`}
                        onClick={() => setActiveTab(tab.key)}
                    >
                        <tab.icon size={14} aria-hidden="true" /> {t(`globalIntegrations.tabs.${tab.key}`)}
                    </button>
                ))}
            </div>

            {/* ── Log Providers Tab ── */}
            {activeTab === "logs" && (
                obsLoading ? (
                    <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <LogProviderPanel integrations={obsIntegrations} onRefresh={fetchObsIntegrations} />
                )
            )}

            {/* ── Metric Providers Tab ── */}
            {activeTab === "metrics" && (
                obsLoading ? (
                    <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <MetricProviderPanel integrations={obsIntegrations} onRefresh={fetchObsIntegrations} />
                )
            )}

            {/* ── Trace Providers Tab ── */}
            {activeTab === "traces" && (
                obsLoading ? (
                    <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>
                ) : (
                    <TraceProviderPanel integrations={obsIntegrations} onRefresh={fetchObsIntegrations} />
                )
            )}

            {/* ── SCM / CI/CD Cards ── */}
            {(activeTab === "scm" || activeTab === "cicd") && (
                <>
                    <IntegrationsSectionHeader
                        title={t(`globalIntegrations.tabs.${activeTab}`)}
                        count={filteredIntegrations.length}
                        description={t(`globalIntegrations.${activeTab}Desc`)}
                        action={canManage && (
                            <Button variant="primary" onClick={openAdd}>
                                <FaPlus aria-hidden="true" />{t("globalIntegrations.addIntegration", "Add Integration")}
                            </Button>
                        )}
                    />
                    {loading ? (
                        <div className="text-center py-5"><Spinner animation="border" variant="primary" /></div>
                    ) : filteredIntegrations.length === 0 ? (
                        <div className="text-center py-5 text-muted">
                            <FaPlug size={40} className="mb-2 opacity-50" />
                            <p>{t("globalIntegrations.noIntegrations", "No integrations yet")}</p>
                        </div>
                    ) : (
                        <Row>
                            {filteredIntegrations.map((int) => {
                                const prov = getProvider(int.provider_type);
                                const Icon = prov.icon;
                                const isVer = verifying[int.id];
                                const verified = int.verification_status === "verified" || int.is_active;
                                const usage = integrationUsage[int.id] || {};

                                return (
                                    <Col key={int.id} xs={12} lg={6} xxl={4} className="mb-4">
                                        <Card className="h-100 shadow-sm border-0 integration-card" style={{ transition: "all 0.2s" }}>
                                            <Card.Body>
                                                {/* Header Row: Icon + Name + Status + Actions */}
                                                <div className="d-flex justify-content-between align-items-start mb-3 gap-2">
                                                    <div className="d-flex align-items-center gap-3" style={{ minWidth: 0 }}>
                                                        <div
                                                            className="rounded-3 p-2 d-flex align-items-center justify-content-center flex-shrink-0"
                                                            style={{ backgroundColor: `${prov.color}15`, width: 48, height: 48 }}
                                                        >
                                                            <Icon size={24} style={{ color: prov.color }} aria-hidden="true" />
                                                        </div>
                                                        <div style={{ minWidth: 0 }}>
                                                            <h5 className="mb-0 fw-semibold">{int.name}</h5>
                                                            <div className="d-flex align-items-center flex-wrap gap-2 text-muted small">
                                                                {/* Providers without a URL (Jenkins) have nothing to link to. */}
                                                                {(int.base_url || prov.url) && (
                                                                    <>
                                                                        <a
                                                                            href={int.base_url || prov.url}
                                                                            target="_blank"
                                                                            rel="noopener noreferrer"
                                                                            className="text-muted text-decoration-none"
                                                                        >
                                                                            {(int.base_url || prov.url).replace(/^https?:\/\//, '')}
                                                                            <FaExternalLinkAlt size={10} className="ms-1" aria-hidden="true" />
                                                                        </a>
                                                                        <span aria-hidden="true">•</span>
                                                                    </>
                                                                )}
                                                                <OverlayTrigger
                                                                    placement="top"
                                                                    overlay={<Tooltip>Created: {new Date(int.created_at).toLocaleString()}</Tooltip>}
                                                                >
                                                                    <span className="d-flex align-items-center gap-1">
                                                                        <FaClock size={10} />
                                                                        {formatTimeAgo(int.created_at)}
                                                                    </span>
                                                                </OverlayTrigger>
                                                            </div>
                                                        </div>
                                                    </div>
                                                    <div className="d-flex align-items-center gap-2 flex-shrink-0">
                                                        <Badge
                                                            bg={verified ? "success" : "warning"}
                                                            className="d-flex align-items-center gap-1 px-2 py-1"
                                                        >
                                                            {verified ? <FaCheck size={10} /> : <FaSync size={10} />}
                                                            {verified ? "Active" : "Pending"}
                                                        </Badge>
                                                        <Dropdown align="end">
                                                            <Dropdown.Toggle
                                                                variant="link"
                                                                className="text-muted p-1"
                                                                style={{ boxShadow: "none" }}
                                                                aria-label={`Actions for ${int.name}`}
                                                                title={`Actions for ${int.name}`}
                                                            >
                                                                <FaEllipsisV size={14} aria-hidden="true" />
                                                            </Dropdown.Toggle>
                                                            <Dropdown.Menu>
                                                                {canManage && (
                                                                <Dropdown.Item onClick={() => openEdit(int)}>
                                                                    <FaEdit className="me-2" />Edit
                                                                </Dropdown.Item>
                                                                )}
                                                                <Dropdown.Item onClick={() => handleSync(int)}>
                                                                    <FaSync className="me-2" />Sync Now
                                                                </Dropdown.Item>
                                                                {canManage && <Dropdown.Divider />}
                                                                {canManage && (
                                                                <Dropdown.Item
                                                                    className="text-danger"
                                                                    onClick={() => { setSelected(int); setShowDeleteModal(true); }}
                                                                >
                                                                    <FaTrash className="me-2" />Delete
                                                                </Dropdown.Item>
                                                                )}
                                                            </Dropdown.Menu>
                                                        </Dropdown>
                                                    </div>
                                                </div>

                                                {/* Capabilities Row */}
                                                <div className="d-flex flex-wrap gap-2 mb-3">
                                                    {prov.caps.map(c => (
                                                        <Badge
                                                            key={c}
                                                            bg="light"
                                                            text="dark"
                                                            className="border fw-normal"
                                                            style={{ fontSize: "0.75rem" }}
                                                        >
                                                            {c === "scm" && "SCM"}
                                                            {c === "cicd" && "CI/CD"}
                                                            {c === "deployments" && "Deployments"}
                                                        </Badge>
                                                    ))}
                                                </div>

                                                {/* Error Alert */}
                                                {int.verification_error && (
                                                    <Alert variant="danger" className="py-2 px-3 mb-3 small d-flex align-items-center gap-2">
                                                        <FaTimes />
                                                        {int.verification_error}
                                                    </Alert>
                                                )}

                                                {/* Usage Stats Bar */}
                                                <div className="bg-light rounded-3 p-3 mb-3">
                                                    <div className="d-flex justify-content-between align-items-center">
                                                        <div className="d-flex align-items-center gap-3">
                                                            <div className="text-center">
                                                                <div className="fw-bold text-primary" style={{ fontSize: "1.25rem" }}>
                                                                    {usage.services_count || 0}
                                                                </div>
                                                                <div className="text-muted small">Services</div>
                                                            </div>
                                                            {usage.last_sync && (
                                                                <>
                                                                    <div className="border-start" style={{ height: 30 }}></div>
                                                                    <div>
                                                                        <div className="d-flex align-items-center gap-1 text-muted small">
                                                                            <FaHistory size={10} />
                                                                            Last sync
                                                                        </div>
                                                                        <div className="small fw-medium">{formatTimeAgo(usage.last_sync)}</div>
                                                                    </div>
                                                                </>
                                                            )}
                                                        </div>
                                                        {usage.services_count > 0 && (
                                                            <a href="#" className="small text-decoration-none d-flex align-items-center gap-1">
                                                                <FaLink size={10} />
                                                                View services
                                                            </a>
                                                        )}
                                                    </div>
                                                </div>

                                                {/* Action Button */}
                                                <Button
                                                    variant={verified ? "outline-success" : "outline-primary"}
                                                    className="w-100 rounded-pill"
                                                    onClick={() => handleVerify(int)}
                                                    disabled={isVer}
                                                >
                                                    {isVer ? (
                                                        <><Spinner size="sm" animation="border" className="me-2" />Verifying...</>
                                                    ) : (
                                                        <><FaSync size={12} className="me-2" />Verify Connection</>
                                                    )}
                                                </Button>
                                            </Card.Body>
                                        </Card>
                                    </Col>
                                );
                            })}
                        </Row>
                    )}
                </>
            )}

            {/* Add/Edit Modal - Enhanced */}
            <Modal show={showModal} onHide={() => setShowModal(false)} centered size="lg">
                <Modal.Header closeButton className="border-bottom-0">
                    <Modal.Title>{isEditing ? t("globalIntegrations.editIntegration", "Edit Integration") : t("globalIntegrations.addNewIntegration", "Add New Integration")}</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <Form onSubmit={handleSubmit}>
                        {/* Provider Selection Grid */}
                        {!isEditing && (
                            <>
                                {/* Only the providers this tab is about: Jenkins is CI/CD, not source control. */}
                                <ChoiceGroup
                                    variant="cards"
                                    className="mb-3"
                                    label={t("globalIntegrations.selectProvider", "Select Provider")}
                                    value={formData.provider_type}
                                    onChange={selectProvider}
                                    options={Object.entries(PROVIDERS)
                                        .filter(([, p]) => (activeTab === "cicd" ? inCicdTab(p) : p.caps.includes("scm")))
                                        .map(([k, p]) => ({
                                            value: k,
                                            label: <span className="d-inline-flex align-items-center gap-2">{React.createElement(p.icon, { size: 18, style: { color: p.color }, "aria-hidden": true })}{p.name}</span>,
                                        }))}
                                />

                                {/* Capability Matrix (collapsible) */}
                                <CapabilityMatrix />
                            </>
                        )}

                        {/* Progressive Disclosure: Config Section */}
                        <Collapse in={isEditing || showConfigSection}>
                            <div>
                                {/* Integration Name */}
                                <Form.Group className="mb-3 mt-4" controlId="integration-name">
                                    <Form.Label>Integration Name</Form.Label>
                                    <Form.Control
                                        type="text"
                                        name="name"
                                        placeholder={`e.g., Company ${PROVIDERS[formData.provider_type]?.name}`}
                                        value={formData.name}
                                        onChange={handleInputChange}
                                        required
                                    />
                                    {!PROVIDERS[formData.provider_type]?.receiveOnly && (
                                    <Form.Text className="text-muted">
                                        <FaInfoCircle size={10} className="me-1" />
                                        Tip: Enter a URL below and we'll auto-suggest a name
                                    </Form.Text>
                                    )}
                                </Form.Group>

                                {/* Provider-specific fields */}
                                <div className="p-3 bg-light rounded-3 mb-3">
                                    <h6 className="mb-3 d-flex align-items-center gap-2">
                                        {React.createElement(PROVIDERS[formData.provider_type]?.icon || FaCloud, { size: 18, style: { color: PROVIDERS[formData.provider_type]?.color } })}
                                        {PROVIDERS[formData.provider_type]?.name} Configuration
                                    </h6>
                                    {renderProviderFields()}
                                </div>

                                {/* Connection Test Result */}
                                {connectionTestResult && (
                                    <Alert
                                        variant={connectionTestResult.success ? "success" : "danger"}
                                        className="d-flex align-items-center gap-2 py-2"
                                    >
                                        {connectionTestResult.success ? <FaCheckCircle /> : <FaExclamationCircle />}
                                        <div>
                                            <strong>{connectionTestResult.success ? "Connection successful!" : "Connection failed"}</strong>
                                            {connectionTestResult.message && (
                                                <div className="small">{connectionTestResult.message}</div>
                                            )}
                                            {connectionTestResult.user_info?.username && (
                                                <div className="small">Connected as: {connectionTestResult.user_info.username}</div>
                                            )}
                                        </div>
                                    </Alert>
                                )}

                                {/* Security note */}
                                {!PROVIDERS[formData.provider_type]?.receiveOnly && (
                                <Alert variant="info" className="py-2 d-flex align-items-center gap-2 small border-0">
                                    <FaLock />
                                    Credentials are encrypted at rest (Fernet: AES-128 with HMAC-SHA256).
                                </Alert>
                                )}
                            </div>
                        </Collapse>

                        <div className="d-flex justify-content-between gap-2 mt-4">
                            {/* Test Connection Button (nothing to test for a GitOps controller) */}
                            {PROVIDERS[formData.provider_type]?.receiveOnly ? <span /> : (
                            <Button
                                variant="outline-secondary"
                                onClick={handleTestConnection}
                                // Jenkins calls its token api_token and Bitbucket app_password
                                // (both mapped to access_token on save); checking only
                                // access_token left the button disabled for them.
                                disabled={testingConnection || !(formData.credentials.access_token
                                    || formData.credentials.api_token || formData.credentials.app_password)}
                                className="d-flex align-items-center gap-2"
                            >
                                {testingConnection ? (
                                    <><Spinner size="sm" animation="border" />Testing...</>
                                ) : (
                                    <><FaFlask />Test Connection</>
                                )}
                            </Button>
                            )}

                            <div className="d-flex gap-2">
                                <Button variant="light" onClick={() => setShowModal(false)} className="px-4">{t("common.cancel", "Cancel")}</Button>
                                <Button variant="primary" type="submit" disabled={saving} className="px-4">
                                    {saving ? <Spinner size="sm" animation="border" /> : isEditing ? "Save Changes" : "Create Integration"}
                                </Button>
                            </div>
                        </div>
                    </Form>
                </Modal.Body>
            </Modal>

            {/* Delete Modal */}
            <Modal show={showDeleteModal} onHide={() => setShowDeleteModal(false)} centered>
                <Modal.Header closeButton className="border-bottom-0"><Modal.Title>Delete Integration</Modal.Title></Modal.Header>
                <Modal.Body>
                    <p>Delete <strong>{selected?.name}</strong>?</p>
                    <Alert variant="warning" className="mb-0 d-flex align-items-start gap-2">
                        <FaInfoCircle className="mt-1" />
                        <div>
                            <strong>Warning:</strong> This action cannot be undone.
                            {integrationUsage[selected?.id]?.services_count > 0 && (
                                <> {integrationUsage[selected?.id]?.services_count} service(s) using this integration will need to be reconfigured.</>
                            )}
                        </div>
                    </Alert>
                </Modal.Body>
                <Modal.Footer className="border-top-0">
                    <Button variant="light" onClick={() => setShowDeleteModal(false)}>Cancel</Button>
                    <Button variant="danger" onClick={handleDelete}>Delete</Button>
                </Modal.Footer>
            </Modal>

            {/* Custom Styles */}
            <style>{`
                .integration-card:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 8px 25px rgba(0,0,0,0.1) !important;
                }
                .dropdown-toggle::after {
                    display: none;
                }
                .cursor-pointer {
                    cursor: pointer;
                }
            `}</style>
        </div>
    );
};

export default SettingsIntegrations;
