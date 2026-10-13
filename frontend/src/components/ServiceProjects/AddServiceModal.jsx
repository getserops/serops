/**
 * AddServiceModal - Modal for adding new services to a project
 * 
 * Unified Service Model (3 types):
 * - Application: Code-based services with SCM binding (GitLab, GitHub, Bitbucket)
 * - Infrastructure: Database, Cache, or Queue
 * - Custom: User-defined service with name and description
 * 
 * CI/CD bindings are handled separately via SCMBinding/CICDBinding models.
 */

import React from "react";
import { Modal, Button, Form, Alert } from "react-bootstrap";
import { useTranslation } from "react-i18next";
import { IntegrationService } from "../../services/integration.service";
import ServiceTypeSelector from "./ServiceTypeSelector";
import {
    CustomServiceForm,
    InfrastructureForm,
    GitLabForm,
    GitHubForm,
    BitbucketForm,
    CICDBindingForm,
} from "./ServiceForms";


const AddServiceModal = ({
    show,
    onHide,
    formData,
    setFormData,
    handleChange,
    handleSubmit,
    verifyGitLabProject,
    verifyGitHubProject,
    verifyBitbucketProject,
    verifyAzureDevOpsProject,
    isSubmitting,
    submitError,
    submitSuccess,
    verifying,
    projectVerified,
    verificationMessage,
    // GitHub-specific verification state
    githubVerifying,
    githubVerified,
    githubVerificationMessage,
    // Bitbucket-specific verification state
    bitbucketVerifying,
    bitbucketVerified,
    bitbucketVerificationMessage,
    // Azure DevOps-specific verification state
    azureDevOpsVerifying,
    azureDevOpsVerified,
    azureDevOpsVerificationMessage,
}) => {
    const { t } = useTranslation();
    const [integrations, setIntegrations] = React.useState([]);

    React.useEffect(() => {
        if (show) {
            fetchIntegrations();
        }
    }, [show]);

    const fetchIntegrations = async () => {
        try {
            const data = await IntegrationService.getAll();
            setIntegrations(data);
        } catch (error) {
            console.error("Failed to fetch integrations", error);
        }
    };

    // Helper to get integrations for a specific provider type
    const getIntegrationsFor = (type) => integrations.filter(i => i.provider_type === type && i.is_active);

    // Determine modal title based on service type
    const getModalTitle = () => {
        if (formData.service_type === "custom") {
            return t('addService.customService');
        }
        if (formData.service_type === "infrastructure") {
            const infraName = formData.infra_type ?
                formData.infra_type.charAt(0).toUpperCase() + formData.infra_type.slice(1) :
                "Service";
            return `${t('addService.infrastructure')} - ${infraName}`;
        }
        // Application type - show SCM provider name if selected
        const scmNames = { gitlab: "GitLab", github: "GitHub", bitbucket: "Bitbucket" };
        const providerName = scmNames[formData.scm_type] || "Application";
        return `Add ${providerName} Service`;
    };


    return (
        <Modal show={show} onHide={onHide} centered size="lg">
            <Modal.Body className="p-0">
                <div className="d-flex flex-column flex-md-row">
                    {/* Left sidebar - service type selection */}
                    <ServiceTypeSelector formData={formData} setFormData={setFormData} />

                    {/* Right section - form fields */}
                    <div className="p-4 flex-grow-1">
                        <div className="d-flex justify-content-between align-items-center mb-4">
                            <h5 className="mb-0">{getModalTitle()}</h5>
                            <Button variant="close" onClick={onHide}></Button>
                        </div>

                        <Form>
                            {submitSuccess && (
                                <Alert variant="success" className="d-flex align-items-center">
                                    <i className="fas fa-check-circle me-2"></i>
                                    {t('addService.addedSuccess')}
                                </Alert>
                            )}

                            {submitError && (
                                <Alert variant="danger" className="d-flex align-items-center">
                                    <i className="fas fa-exclamation-circle me-2"></i>
                                    {submitError}
                                </Alert>
                            )}

                            {/* Render appropriate form based on service type */}
                            {formData.service_type === "custom" && (
                                <CustomServiceForm formData={formData} handleChange={handleChange} />
                            )}

                            {formData.service_type === "infrastructure" && (
                                <InfrastructureForm formData={formData} handleChange={handleChange} />
                            )}

                            {/* Application type - render SCM form based on selected provider */}
                            {formData.service_type === "application" && formData.scm_type === "gitlab" && (
                                <GitLabForm
                                    formData={formData}
                                    handleChange={handleChange}
                                    verifyGitLabProject={verifyGitLabProject}
                                    verifying={verifying}
                                    projectVerified={projectVerified}
                                    verificationMessage={verificationMessage}
                                    integrations={getIntegrationsFor('gitlab')}
                                />
                            )}

                            {formData.service_type === "application" && formData.scm_type === "github" && (
                                <GitHubForm
                                    formData={formData}
                                    handleChange={handleChange}
                                    verifyGitHubProject={verifyGitHubProject}
                                    verifying={githubVerifying}
                                    projectVerified={githubVerified}
                                    verificationMessage={githubVerificationMessage}
                                    integrations={getIntegrationsFor('github')}
                                />
                            )}

                            {formData.service_type === "application" && formData.scm_type === "bitbucket" && (
                                <BitbucketForm
                                    formData={formData}
                                    handleChange={handleChange}
                                    verifyBitbucketProject={verifyBitbucketProject}
                                    verifying={bitbucketVerifying}
                                    projectVerified={bitbucketVerified}
                                    verificationMessage={bitbucketVerificationMessage}
                                    integrations={getIntegrationsFor('bitbucket')}
                                />
                            )}

                            {/* CI/CD Binding Form (when enabled for Application type) */}
                            {formData.service_type === "application" && formData.add_cicd && (
                                <CICDBindingForm
                                    formData={formData}
                                    handleChange={handleChange}
                                    integrations={integrations}
                                    cicdProvider={formData.cicd_provider || formData.scm_type}
                                />
                            )}


                            <hr className="my-4" />

                            {/* Footer buttons */}
                            <div className="d-flex justify-content-end">
                                <Button
                                    variant="light"
                                    onClick={onHide}
                                    className="me-2 rounded-pill px-4"
                                    disabled={isSubmitting}
                                >
                                    {t('common.cancel')}
                                </Button>
                                <Button
                                    variant="primary"
                                    onClick={handleSubmit}
                                    className="rounded-pill px-4"
                                    disabled={
                                        isSubmitting ||
                                        (formData.service_type === "application" &&
                                            formData.scm_type === "gitlab" &&
                                            !projectVerified) ||
                                        (formData.service_type === "application" &&
                                            formData.scm_type === "github" &&
                                            !githubVerified) ||
                                        (formData.service_type === "application" &&
                                            formData.scm_type === "bitbucket" &&
                                            !bitbucketVerified)
                                    }

                                >
                                    {isSubmitting ? (
                                        <>
                                            <span
                                                className="spinner-border spinner-border-sm me-2"
                                                role="status"
                                                aria-hidden="true"
                                            ></span>
                                            {t('addService.adding')}
                                        </>
                                    ) : (
                                        t('addService.addService')
                                    )}
                                </Button>
                            </div>
                        </Form>
                    </div>
                </div>
            </Modal.Body>
        </Modal>
    );
};

export default AddServiceModal;
