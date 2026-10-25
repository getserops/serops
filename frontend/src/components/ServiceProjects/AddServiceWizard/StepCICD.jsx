/**
 * StepCICD - Step 3: Add CI/CD Pipeline (Optional)
 * For Application services - optionally configure CI/CD
 */

import React from "react";
import { Form } from "react-bootstrap";
import { FaGitlab, FaGithub, FaJenkins, FaMicrosoft, FaRocket, FaForward } from "react-icons/fa";
import { SiArgo, SiFlux } from "react-icons/si";

const cicdProviders = [
    { id: "gitlab", name: "GitLab CI", icon: FaGitlab, color: "#FC6D26" },
    { id: "github", name: "GitHub Actions", icon: FaGithub, color: "#24292F" },
    { id: "jenkins", name: "Jenkins", icon: FaJenkins, color: "#D33833" },
    { id: "azure_devops", name: "Azure DevOps", icon: FaMicrosoft, color: "#0078D7" },
    { id: "argocd", name: "Argo CD", icon: SiArgo, color: "#EF7B4D" },
    { id: "flux", name: "Flux", icon: SiFlux, color: "#5468FF" },
];

const pipelineTypes = [
    { id: "build", label: "Build Pipeline" },
    { id: "deploy", label: "Deployment Pipeline" },
    { id: "test", label: "Test Pipeline" },
    { id: "release", label: "Release Pipeline" },
];

const StepCICD = ({
    formData,
    updateFormData,
    integrations
}) => {
    // Filter CI/CD integrations
    const getCicdIntegrations = (provider) => {
        return integrations.filter(i => i.provider_type === provider && i.is_active);
    };

    const currentProviderIntegrations = getCicdIntegrations(formData.cicdProvider);

    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">Add CI/CD Pipeline?</h5>
            <p className="wizard-step-subtitle">
                Connect a build or deployment pipeline to this service.
            </p>

            {/* Yes/No Toggle */}
            <div className="optional-toggle">
                <div
                    className={`optional-card ${formData.addCicd ? 'selected' : ''}`}
                    onClick={() => updateFormData({
                        addCicd: true,
                        cicdProvider: formData.scmProvider || 'gitlab'
                    })}
                >
                    <div className="optional-card-icon"><FaRocket /></div>
                    <div className="optional-card-label">Yes, set up CI/CD</div>
                </div>
                <div
                    className={`optional-card ${!formData.addCicd ? 'selected' : ''}`}
                    onClick={() => updateFormData({ addCicd: false })}
                >
                    <div className="optional-card-icon"><FaForward /></div>
                    <div className="optional-card-label">Skip for now</div>
                </div>
            </div>

            {/* CI/CD Configuration (if enabled) */}
            {formData.addCicd && (
                <div className="optional-section mt-3">
                    {/* Provider Selection */}
                    <div className="wizard-form-section">
                        <span className="wizard-form-label d-block" id="wizard-cicd-provider">CI/CD Provider</span>
                        <div className="provider-buttons" role="group" aria-labelledby="wizard-cicd-provider">
                            {cicdProviders.map((provider) => {
                                const Icon = provider.icon;
                                const isActive = formData.cicdProvider === provider.id;

                                return (
                                    <button
                                        key={provider.id}
                                        type="button"
                                        aria-pressed={isActive}
                                        className={`provider-btn ${isActive ? 'active' : ''}`}
                                        onClick={() => updateFormData({
                                            cicdProvider: provider.id,
                                            cicdIntegrationId: null
                                        })}
                                        style={isActive ? { background: provider.color, borderColor: provider.color } : {}}
                                    >
                                        <Icon className="me-2" />
                                        {provider.name}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Integration Selection */}
                    <div className="wizard-form-section">
                        <label className="wizard-form-label" htmlFor="wizard-cicd-1">Integration</label>
                        {currentProviderIntegrations.length === 0 ? (
                            <div className="text-muted small">
                                No {formData.cicdProvider} integrations configured.
                                <a href="/dash/settings/integrations" className="ms-1">Add one in Settings</a>
                            </div>
                        ) : (
                            <Form.Select id="wizard-cicd-1"
                                value={formData.cicdIntegrationId || ""}
                                onChange={(e) => updateFormData({
                                    cicdIntegrationId: parseInt(e.target.value)
                                })}
                                className="rounded-3"
                            >
                                <option value="">Select integration...</option>
                                {currentProviderIntegrations.map(integration => (
                                    <option key={integration.id} value={integration.id}>
                                        {integration.name}
                                    </option>
                                ))}
                            </Form.Select>
                        )}
                    </div>

                    {/* Pipeline Type */}
                    <div className="wizard-form-section">
                        <label className="wizard-form-label" htmlFor="wizard-cicd-2">Pipeline Type</label>
                        <Form.Select id="wizard-cicd-2"
                            value={formData.cicdType || "build"}
                            onChange={(e) => updateFormData({ cicdType: e.target.value })}
                            className="rounded-3"
                        >
                            {pipelineTypes.map(type => (
                                <option key={type.id} value={type.id}>
                                    {type.label}
                                </option>
                            ))}
                        </Form.Select>
                    </div>

                    {/* Info text */}
                    {(formData.cicdProvider === 'gitlab' || formData.cicdProvider === 'github') && (
                        <div className="text-muted small mt-2">
                            ℹ️ Pipeline will be auto-detected from your repository configuration.
                        </div>
                    )}
                </div>
            )}

            {!formData.addCicd && (
                <div className="text-muted small mt-3">
                    You can add CI/CD pipelines later from the Service Details page.
                </div>
            )}
        </div>
    );
};

export default StepCICD;
