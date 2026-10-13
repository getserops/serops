/**
 * ServiceTypeSelector - Left sidebar for selecting service type in AddServiceModal
 * 
 * NEW UNIFIED MODEL:
 * - Application: Code-based services with optional SCM/CICD bindings
 * - Infrastructure: Non-code services (database, cache, queue)
 * - Custom: Manual entries for legacy/external systems
 */

import React from "react";
import { Button } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { FaCode, FaServer, FaEdit } from "react-icons/fa";

// Service type option card component
const TypeCard = ({ id, name, icon: Icon, label, description, selected, onClick }) => (
    <div
        className={`service-type-card p-3 rounded-3 transition-all ${selected
            ? "border-2 border-primary bg-primary bg-opacity-5 shadow-sm"
            : "border hover-shadow"
            }`}
        onClick={onClick}
        style={{ cursor: "pointer" }}
    >
        <div className="d-flex align-items-center">
            {Icon && <Icon className={`me-2 ${selected ? "text-primary" : "text-muted"}`} size={20} />}
            <div className="form-check mb-0">
                <input
                    className="form-check-input"
                    type="radio"
                    id={id}
                    name={name}
                    checked={selected}
                    onChange={() => { }}
                    readOnly
                />
            </div>
            <label htmlFor={id} className="ms-1 mb-0 fw-bold" style={{ cursor: "pointer" }}>
                {label}
            </label>
        </div>
        {description && <p className="text-muted small mt-2 mb-0 ms-4 ps-3">{description}</p>}
    </div>
);

// Subtype button component
const SubtypeButton = ({ label, selected, onClick }) => (
    <Button
        variant={selected ? "primary" : "outline-secondary"}
        size="sm"
        onClick={onClick}
        className="rounded-pill"
    >
        {label}
    </Button>
);

const ServiceTypeSelector = ({ formData, setFormData }) => {
    const { t } = useTranslation();

    const handleTypeChange = (type) => {
        setFormData((prev) => ({
            ...prev,
            service_type: type,
            // Reset binding selections when type changes
            scm_type: type === "application" ? "gitlab" : "",
            cicd_type: "",
            infra_type: type === "infrastructure" ? "database" : "",
        }));
    };

    const handleSubtypeChange = (subtype) => {
        setFormData((prev) => ({
            ...prev,
            subtype: subtype,
            infra_type: subtype, // Keep backwards compat
        }));
    };

    return (
        <div className="bg-primary bg-opacity-10 p-4" style={{ minWidth: "280px" }}>
            <h5 className="mb-3 text-primary fw-bold">{t('addService.title')}</h5>
            <p className="text-muted small mb-4">
                Select the type of service you want to add to your project.
            </p>

            <div className="d-flex flex-column gap-3">
                {/* Application Service Option */}
                <TypeCard
                    id="application-service"
                    name="service_type"
                    icon={FaCode}
                    label="Application"
                    description="Microservices, APIs, backends, frontends with optional code repository and CI/CD pipeline connections."
                    selected={formData.service_type === "application"}
                    onClick={() => handleTypeChange("application")}
                />

                {/* Infrastructure Service Option */}
                <TypeCard
                    id="infrastructure-service"
                    name="service_type"
                    icon={FaServer}
                    label="Infrastructure"
                    description="Databases, caches, message queues, and other non-code infrastructure."
                    selected={formData.service_type === "infrastructure"}
                    onClick={() => handleTypeChange("infrastructure")}
                />

                {/* Custom Service Option */}
                <TypeCard
                    id="custom-service"
                    name="service_type"
                    icon={FaEdit}
                    label="Custom"
                    description="Manual service entry for legacy systems or external services."
                    selected={formData.service_type === "custom"}
                    onClick={() => handleTypeChange("custom")}
                />

                {/* Application: SCM Provider Selection */}
                {formData.service_type === "application" && (
                    <div className="mt-2 p-3 bg-light rounded-3">
                        <p className="text-muted small mb-2 fw-medium">
                            Code Repository Provider:
                        </p>
                        <div className="d-flex gap-2 flex-wrap">
                            <SubtypeButton
                                label="GitLab"
                                selected={formData.scm_type === "gitlab"}
                                onClick={() => setFormData((prev) => ({
                                    ...prev,
                                    scm_type: "gitlab",
                                    // Smart default: set CI/CD to same provider
                                    cicd_provider: prev.add_cicd ? "gitlab" : prev.cicd_provider
                                }))}
                            />
                            <SubtypeButton
                                label="GitHub"
                                selected={formData.scm_type === "github"}
                                onClick={() => setFormData((prev) => ({
                                    ...prev,
                                    scm_type: "github",
                                    cicd_provider: prev.add_cicd ? "github" : prev.cicd_provider
                                }))}
                            />
                            <SubtypeButton
                                label="Bitbucket"
                                selected={formData.scm_type === "bitbucket"}
                                onClick={() => setFormData((prev) => ({
                                    ...prev,
                                    scm_type: "bitbucket",
                                    cicd_provider: prev.add_cicd ? "bitbucket" : prev.cicd_provider
                                }))}
                            />
                        </div>

                        {/* CI/CD Pipeline Toggle */}
                        <div className="mt-3 pt-3 border-top">
                            <div className="form-check">
                                <input
                                    className="form-check-input"
                                    type="checkbox"
                                    id="add-cicd-toggle"
                                    checked={formData.add_cicd || false}
                                    onChange={(e) => setFormData((prev) => ({
                                        ...prev,
                                        add_cicd: e.target.checked,
                                        // Smart default: use same provider as SCM
                                        cicd_provider: e.target.checked ? (prev.scm_type || "gitlab") : "",
                                        cicd_type: e.target.checked ? "build" : "",
                                    }))}
                                />
                                <label className="form-check-label small" htmlFor="add-cicd-toggle">
                                    <strong>Add CI/CD Pipeline</strong>
                                    <span className="text-muted ms-1">(optional)</span>
                                </label>
                            </div>

                            {/* CI/CD Provider Selection (when enabled) */}
                            {formData.add_cicd && (
                                <div className="mt-2 ps-4">
                                    <p className="text-muted small mb-2">CI/CD Provider:</p>
                                    <div className="d-flex gap-2 flex-wrap">
                                        <SubtypeButton
                                            label="GitLab CI"
                                            selected={formData.cicd_provider === "gitlab"}
                                            onClick={() => setFormData((prev) => ({ ...prev, cicd_provider: "gitlab" }))}
                                        />
                                        <SubtypeButton
                                            label="GitHub Actions"
                                            selected={formData.cicd_provider === "github"}
                                            onClick={() => setFormData((prev) => ({ ...prev, cicd_provider: "github" }))}
                                        />
                                        <SubtypeButton
                                            label="Jenkins"
                                            selected={formData.cicd_provider === "jenkins"}
                                            onClick={() => setFormData((prev) => ({ ...prev, cicd_provider: "jenkins" }))}
                                        />
                                        <SubtypeButton
                                            label="Azure DevOps"
                                            selected={formData.cicd_provider === "azure_devops"}
                                            onClick={() => setFormData((prev) => ({ ...prev, cicd_provider: "azure_devops" }))}
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Infrastructure: Subtype Selection */}
                {formData.service_type === "infrastructure" && (
                    <div className="mt-2 p-3 bg-light rounded-3">
                        <p className="text-muted small mb-2 fw-medium">
                            Infrastructure Type:
                        </p>
                        <div className="d-flex gap-2 flex-wrap">
                            <SubtypeButton
                                label="Database"
                                selected={formData.infra_type === "database"}
                                onClick={() => handleSubtypeChange("database")}
                            />
                            <SubtypeButton
                                label="Cache"
                                selected={formData.infra_type === "cache"}
                                onClick={() => handleSubtypeChange("cache")}
                            />
                            <SubtypeButton
                                label="Queue"
                                selected={formData.infra_type === "queue"}
                                onClick={() => handleSubtypeChange("queue")}
                            />
                            <SubtypeButton
                                label="Other"
                                selected={formData.infra_type === "other"}
                                onClick={() => handleSubtypeChange("other")}
                            />
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default ServiceTypeSelector;
