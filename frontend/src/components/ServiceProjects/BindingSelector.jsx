/**
 * BindingSelector - Component for selecting SCM and CI/CD bindings
 * 
 * Features:
 * - Select integration (GitLab, GitHub, Bitbucket, Jenkins, etc.)
 * - Browse/search repositories or pipelines from the integration
 * - Supports both SCM (single) and CI/CD (multiple) bindings
 */

import React from "react";
import { Form, Button, Card, Spinner, Alert, Badge } from "react-bootstrap";
import { FaPlus, FaTrash, FaSync, FaPlug, FaExternalLinkAlt } from "react-icons/fa";
import { Link } from "react-router-dom";
import { IntegrationService } from "../../services/integration.service";

/**
 * Provider display names for UI
 */
const PROVIDER_NAMES = {
    gitlab: "GitLab",
    github: "GitHub",
    bitbucket: "Bitbucket",
    azure_devops: "Azure DevOps",
    jenkins: "Jenkins",
    argocd: "Argo CD",
    flux: "Flux",
};

/**
 * SCM provider types (must match SettingsIntegrations PROVIDERS with "scm" capability)
 */
const SCM_PROVIDERS = ["gitlab", "github", "bitbucket", "azure_devops"];

/**
 * CI/CD provider types (must match SettingsIntegrations PROVIDERS with "cicd" capability)
 */
const CICD_PROVIDERS = ["gitlab", "github", "azure_devops", "jenkins", "bitbucket", "argocd", "flux"];

/**
 * BindingSelector - Unified component for selecting SCM or CI/CD bindings
 * 
 * Props:
 * - type: "scm" | "cicd" - Type of binding
 * - integrations: Array of available integrations (filtered by provider type)
 * - value: Current selected value(s)
 * - onChange: Callback when selection changes
 * - multiple: boolean - Allow multiple selections (for CI/CD)
 * - disabled: boolean - Disable the selector
 */
const BindingSelector = ({
    type = "scm",
    integrations = [],
    value = type === "cicd" ? [] : null,
    onChange,
    multiple = false,
    disabled = false,
    label,
}) => {
    const [selectedIntegrationId, setSelectedIntegrationId] = React.useState("");
    const [repos, setRepos] = React.useState([]);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState(null);

    const providerTypes = type === "scm" ? SCM_PROVIDERS : CICD_PROVIDERS;
    const filteredIntegrations = integrations.filter(
        int => providerTypes.includes(int.provider_type) && int.is_active
    );
    const hasIntegrations = filteredIntegrations.length > 0;

    // Fetch repos when integration is selected
    React.useEffect(() => {
        if (selectedIntegrationId) {
            fetchRepos();
        } else {
            setRepos([]);
        }
    }, [selectedIntegrationId]);

    const fetchRepos = async () => {
        setLoading(true);
        setError(null);
        try {
            const data = await IntegrationService.getRepos(selectedIntegrationId);
            if (Array.isArray(data)) {
                setRepos(data);
            } else if (data && Array.isArray(data.results)) {
                setRepos(data.results);
            } else {
                setRepos([]);
            }
        } catch (err) {
            console.error("Failed to load repos:", err);
            setError("Failed to load repositories");
            setRepos([]);
        } finally {
            setLoading(false);
        }
    };

    const handleIntegrationChange = (e) => {
        setSelectedIntegrationId(e.target.value);
    };

    const handleRepoSelect = (e) => {
        const selectedId = e.target.value;
        const selectedRepo = repos.find(r => String(r.id) === selectedId || r.full_name === selectedId);

        if (!selectedRepo) return;

        const integration = filteredIntegrations.find(i => String(i.id) === selectedIntegrationId);
        const binding = {
            integration_id: selectedIntegrationId,
            provider_type: integration?.provider_type,
            repository_id: selectedRepo.id || selectedRepo.full_name,
            repository_name: selectedRepo.full_name || selectedRepo.name,
            repository_url: selectedRepo.web_url || selectedRepo.html_url || "",
        };

        if (multiple) {
            // For CI/CD, add to array
            const exists = value.some(v =>
                v.repository_id === binding.repository_id &&
                v.integration_id === binding.integration_id
            );
            if (!exists) {
                onChange([...value, binding]);
            }
        } else {
            // For SCM, replace
            onChange(binding);
        }
    };

    const handleRemoveBinding = (index) => {
        if (multiple) {
            onChange(value.filter((_, i) => i !== index));
        } else {
            onChange(null);
        }
    };

    // No integrations available
    if (!hasIntegrations) {
        return (
            <Alert variant="info" className="d-flex align-items-center gap-2">
                <FaPlug className="flex-shrink-0" />
                <div className="flex-grow-1">
                    <strong>No {type.toUpperCase()} integrations configured.</strong>
                    <p className="mb-0 small">
                        Connect an integration to enable {type === "scm" ? "repository" : "pipeline"} binding.
                    </p>
                </div>
                <Link
                    to="/dash/settings/integrations"
                    className="btn btn-sm btn-outline-primary d-flex align-items-center gap-1"
                >
                    <span>Add Integration</span>
                    <FaExternalLinkAlt size={10} />
                </Link>
            </Alert>
        );
    }

    return (
        <div className="binding-selector">
            {label && <Form.Label className="fw-bold">{label}</Form.Label>}

            {/* Integration Selector */}
            <div className="d-flex gap-2 mb-2">
                <Form.Select
                    value={selectedIntegrationId}
                    onChange={handleIntegrationChange}
                    disabled={disabled}
                    className="flex-grow-1"
                >
                    <option value="">Select Integration...</option>
                    {filteredIntegrations.map(int => (
                        <option key={int.id} value={int.id}>
                            {int.name} ({PROVIDER_NAMES[int.provider_type]})
                        </option>
                    ))}
                </Form.Select>
            </div>

            {/* Repository/Pipeline Selector */}
            {selectedIntegrationId && (
                <div className="d-flex gap-2 mb-3">
                    <Form.Select
                        onChange={handleRepoSelect}
                        disabled={disabled || loading}
                        className="flex-grow-1"
                        value=""
                    >
                        <option value="">
                            {loading ? "Loading..." : error ? "Error loading" : `Select ${type === "scm" ? "Repository" : "Pipeline"}...`}
                        </option>
                        {repos.map(repo => (
                            <option key={repo.id || repo.full_name} value={repo.id || repo.full_name}>
                                {repo.full_name || repo.name}
                            </option>
                        ))}
                    </Form.Select>
                    <Button
                        variant="outline-secondary"
                        onClick={fetchRepos}
                        disabled={loading}
                        title="Refresh"
                    >
                        {loading ? <Spinner size="sm" animation="border" /> : <FaSync />}
                    </Button>
                </div>
            )}

            {/* Selected Bindings Display */}
            {multiple && value.length > 0 && (
                <div className="selected-bindings mb-2">
                    {value.map((binding, index) => (
                        <Badge
                            key={index}
                            bg="primary"
                            className="me-2 mb-1 d-inline-flex align-items-center gap-1 py-2 px-2"
                        >
                            <span>{binding.repository_name}</span>
                            <Button
                                variant="link"
                                size="sm"
                                className="text-white p-0 ms-1"
                                onClick={() => handleRemoveBinding(index)}
                                disabled={disabled}
                            >
                                <FaTrash size={10} />
                            </Button>
                        </Badge>
                    ))}
                </div>
            )}

            {/* Single binding display */}
            {!multiple && value && (
                <Card className="mb-2">
                    <Card.Body className="py-2 d-flex justify-content-between align-items-center">
                        <div>
                            <Badge bg="secondary" className="me-2">
                                {PROVIDER_NAMES[value.provider_type]}
                            </Badge>
                            <span>{value.repository_name}</span>
                        </div>
                        <Button
                            variant="link"
                            className="text-danger p-0"
                            onClick={() => handleRemoveBinding()}
                            disabled={disabled}
                        >
                            <FaTrash />
                        </Button>
                    </Card.Body>
                </Card>
            )}

            {error && <Form.Text className="text-danger">{error}</Form.Text>}
        </div>
    );
};

export default BindingSelector;
