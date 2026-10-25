/**
 * AddServiceWizard - Main wizard container for adding services
 * 
 * Replaces the old split-panel modal with a clean step-by-step flow:
 * Step 1: Choose type (Application, Infrastructure, Custom)
 * Step 2: Configure details (varies by type)
 * Step 3: Add CI/CD (optional, Application only)
 */

import React, { useState, useEffect } from "react";
import { Modal, Button, Alert, Spinner } from "react-bootstrap";
import { FaArrowLeft, FaArrowRight, FaCheck } from "react-icons/fa";

import WizardProgress from "./WizardProgress";
import StepTypeSelect from "./StepTypeSelect";
import StepConnectRepo from "./StepConnectRepo";
import StepInfraDetails from "./StepInfraDetails";
import StepCustomDetails from "./StepCustomDetails";
import StepCICD from "./StepCICD";

import { IntegrationService } from "../../../services/integration.service";
import { ProjectService } from "../../../services/project.service";

import "./wizard.css";

// Initial form state
const INITIAL_STATE = {
    // Step 1
    serviceType: null,

    // Step 2 - Application
    scmProvider: "gitlab",
    integrationId: null,
    repositoryId: null,
    repositoryName: "",
    serviceName: "",
    noRepo: false,

    // Step 2 - Infrastructure
    infraType: "database",
    infraProvider: "",
    description: "",

    // Step 3 - CI/CD
    addCicd: false,
    cicdProvider: "gitlab",
    cicdIntegrationId: null,
    cicdType: "build",
};

const AddServiceWizard = ({ show, onHide, projectId, onServiceCreated }) => {
    // Wizard state
    const [currentStep, setCurrentStep] = useState(1);
    const [formData, setFormData] = useState(INITIAL_STATE);

    // Integrations
    const [integrations, setIntegrations] = useState([]);
    const [loadingIntegrations, setLoadingIntegrations] = useState(true);

    // Verification
    const [verifying, setVerifying] = useState(false);
    const [verified, setVerified] = useState(false);
    const [verificationMessage, setVerificationMessage] = useState("");

    // Submission
    const [submitting, setSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const [submitSuccess, setSubmitSuccess] = useState(false);

    // Calculate total steps based on service type
    const getTotalSteps = () => {
        if (formData.serviceType === "application") return 3;
        return 2;
    };

    const getStepLabels = () => {
        if (formData.serviceType === "application") {
            return ["Choose Type", "Connect Code", "CI/CD"];
        }
        if (formData.serviceType === "infrastructure") {
            return ["Choose Type", "Details"];
        }
        if (formData.serviceType === "custom") {
            return ["Choose Type", "Details"];
        }
        return ["Choose Type", "Configure"];
    };

    // Fetch integrations on mount
    useEffect(() => {
        const fetchIntegrations = async () => {
            try {
                const data = await IntegrationService.getAll();
                setIntegrations(data || []);
            } catch (error) {
                console.error("Failed to fetch integrations:", error);
            } finally {
                setLoadingIntegrations(false);
            }
        };

        if (show) {
            fetchIntegrations();
        }
    }, [show]);

    // Reset on close/open
    useEffect(() => {
        if (show) {
            setCurrentStep(1);
            setFormData(INITIAL_STATE);
            setVerified(false);
            setVerificationMessage("");
            setSubmitError(null);
            setSubmitSuccess(false);
        }
    }, [show]);

    // Update form data helper
    const updateFormData = (updates) => {
        setFormData(prev => ({ ...prev, ...updates }));
        setSubmitError(null);
    };

    // Type selection handler (auto-advances to step 2)
    const handleTypeSelect = (type) => {
        updateFormData({
            serviceType: type,
            // Set smart defaults for CI/CD
            cicdProvider: type === "application" ? formData.scmProvider : "gitlab"
        });
        setCurrentStep(2);
    };

    // Verify repository connection
    const handleVerify = async () => {
        if (!formData.integrationId || !formData.repositoryId) return;

        setVerifying(true);
        setVerificationMessage("");

        try {
            // Use appropriate verification based on provider
            let result;
            if (formData.scmProvider === "gitlab") {
                result = await ProjectService.VerifyGitLabProject({
                    project_id: formData.repositoryId,
                    integration_id: formData.integrationId
                });
            } else if (formData.scmProvider === "github") {
                result = await ProjectService.VerifyGitHubProject({
                    github_repo: formData.repositoryName,
                    integration_id: formData.integrationId
                });
            } else {
                // For other providers, assume verified if we have the data
                result = { success: true };
            }

            if (result.error) {
                setVerificationMessage(result.error);
                setVerified(false);
            } else {
                setVerified(true);
            }
        } catch {
            setVerificationMessage("Verification failed");
            setVerified(false);
        } finally {
            setVerifying(false);
        }
    };

    // Navigation
    const canGoNext = () => {
        if (currentStep === 1) {
            return !!formData.serviceType;
        }
        if (currentStep === 2) {
            if (formData.serviceType === "application") {
                if (formData.noRepo) return !!formData.serviceName?.trim();
                return formData.integrationId && formData.repositoryId;
            }
            if (formData.serviceType === "infrastructure" || formData.serviceType === "custom") {
                return !!formData.serviceName;
            }
        }
        return true;
    };

    const handleNext = () => {
        if (currentStep < getTotalSteps()) {
            setCurrentStep(currentStep + 1);
        }
    };

    const handleBack = () => {
        if (currentStep > 1) {
            setCurrentStep(currentStep - 1);
        }
    };

    // Submit service
    const handleSubmit = async () => {
        setSubmitting(true);
        setSubmitError(null);

        try {
            let result;
            let createdServiceId = null;

            // Create service based on type
            if (formData.serviceType === "application") {
                const payload = {
                    service_type: "application",
                    status: "Active",
                    name: formData.serviceName || formData.repositoryName,
                };

                if (formData.noRepo) {
                    result = await ProjectService.AddApplicationService(projectId, {
                        name: formData.serviceName.trim(),
                    });
                } else if (formData.scmProvider === "gitlab") {
                    payload.project_id = formData.repositoryId;
                    payload.integration_id = formData.integrationId;
                    result = await ProjectService.AddGitLabProjectAsService(projectId, payload);
                } else if (formData.scmProvider === "github") {
                    payload.github_repo = formData.repositoryName;
                    payload.integration_id = formData.integrationId;
                    result = await ProjectService.AddGitHubProjectAsService(projectId, payload);
                } else if (formData.scmProvider === "bitbucket") {
                    payload.bitbucket_repo = formData.repositoryName;
                    payload.integration_id = formData.integrationId;
                    result = await ProjectService.AddBitbucketProjectAsService(projectId, payload);
                }

                if (result?.id) {
                    createdServiceId = result.id;
                }

                // Create CI/CD binding if enabled
                if (formData.addCicd && formData.cicdIntegrationId && createdServiceId) {
                    try {
                        await ProjectService.addCICDBinding(createdServiceId, {
                            integration_id: formData.cicdIntegrationId,
                            binding_type: formData.cicdType || "build",
                            auto_trigger: true,
                        });
                    } catch (cicdError) {
                        console.error("Failed to create CI/CD binding:", cicdError);
                        // Don't fail the whole operation
                    }
                }
            } else if (formData.serviceType === "infrastructure") {
                result = await ProjectService.AddInfraService(projectId, {
                    service_type: "infrastructure",
                    subtype: formData.infraType,
                    name: formData.serviceName,
                    description: formData.description,
                    provider: formData.infraProvider,
                    status: "Active",
                });
            } else if (formData.serviceType === "custom") {
                result = await ProjectService.AddCustomService(projectId, {
                    service_type: "custom",
                    name: formData.serviceName,
                    description: formData.description,
                    status: "Active",
                });
            }

            if (result?.error) {
                setSubmitError(result.error);
                return;
            }

            setSubmitSuccess(true);

            // Close and refresh after success
            setTimeout(() => {
                onHide();
                if (onServiceCreated) {
                    onServiceCreated();
                }
            }, 1000);

        } catch (error) {
            console.error("Error creating service:", error);
            setSubmitError(error.response?.data?.error || "Failed to create service");
        } finally {
            setSubmitting(false);
        }
    };

    // Render current step
    const renderStep = () => {
        switch (currentStep) {
            case 1:
                return (
                    <StepTypeSelect
                        selectedType={formData.serviceType}
                        onTypeSelect={handleTypeSelect}
                    />
                );
            case 2:
                if (formData.serviceType === "application") {
                    return (
                        <StepConnectRepo
                            formData={formData}
                            updateFormData={updateFormData}
                            integrations={integrations}
                            onVerify={handleVerify}
                            verifying={verifying}
                            verified={verified}
                            verificationMessage={verificationMessage}
                        />
                    );
                }
                if (formData.serviceType === "infrastructure") {
                    return (
                        <StepInfraDetails
                            formData={formData}
                            updateFormData={updateFormData}
                        />
                    );
                }
                return (
                    <StepCustomDetails
                        formData={formData}
                        updateFormData={updateFormData}
                    />
                );
            case 3:
                return (
                    <StepCICD
                        formData={formData}
                        updateFormData={updateFormData}
                        integrations={integrations}
                    />
                );
            default:
                return null;
        }
    };

    const isLastStep = currentStep === getTotalSteps();

    return (
        <Modal show={show} onHide={onHide} size="lg" centered aria-labelledby="add-service-title">
            <Modal.Header closeButton className="border-0 pb-0">
                <Modal.Title id="add-service-title" className="fw-bold">Add New Service</Modal.Title>
            </Modal.Header>

            <Modal.Body className="pt-3">
                {/* Progress indicator (hidden on step 1) */}
                {currentStep > 1 && (
                    <WizardProgress
                        currentStep={currentStep}
                        totalSteps={getTotalSteps()}
                        stepLabels={getStepLabels()}
                    />
                )}

                {/* Loading state */}
                {loadingIntegrations && currentStep > 1 && formData.serviceType === "application" ? (
                    <div className="text-center py-5">
                        <Spinner animation="border" variant="primary" />
                        <p className="text-muted mt-2">Loading integrations...</p>
                    </div>
                ) : (
                    renderStep()
                )}

                {/* Error message */}
                {submitError && (
                    <Alert variant="danger" className="mt-3">
                        {submitError}
                    </Alert>
                )}

                {/* Success message */}
                {submitSuccess && (
                    <Alert variant="success" className="mt-3">
                        <FaCheck className="me-2" />
                        Service created successfully!
                    </Alert>
                )}
            </Modal.Body>

            <Modal.Footer className="border-0 pt-0">
                <div className="wizard-actions w-100">
                    <div className="wizard-actions-left">
                        {currentStep > 1 && (
                            <Button
                                variant="outline-secondary"
                                onClick={handleBack}
                                disabled={submitting}
                                className="rounded-pill px-4"
                            >
                                <FaArrowLeft className="me-2" />
                                Back
                            </Button>
                        )}
                    </div>

                    <div className="wizard-actions-right">
                        <Button
                            variant="light"
                            onClick={onHide}
                            disabled={submitting}
                            className="rounded-pill px-4"
                        >
                            Cancel
                        </Button>

                        {currentStep === 1 ? (
                            // Step 1: Type selection auto-advances on click
                            null
                        ) : isLastStep ? (
                            <Button
                                variant="primary"
                                onClick={handleSubmit}
                                disabled={submitting || !canGoNext()}
                                className="rounded-pill px-4"
                            >
                                {submitting ? (
                                    <>
                                        <Spinner size="sm" className="me-2" />
                                        Creating...
                                    </>
                                ) : (
                                    <>
                                        <FaCheck className="me-2" />
                                        Create Service
                                    </>
                                )}
                            </Button>
                        ) : (
                            <Button
                                variant="primary"
                                onClick={handleNext}
                                disabled={!canGoNext()}
                                className="rounded-pill px-4"
                            >
                                Next
                                <FaArrowRight className="ms-2" />
                            </Button>
                        )}
                    </div>
                </div>
            </Modal.Footer>
        </Modal>
    );
};

export default AddServiceWizard;
