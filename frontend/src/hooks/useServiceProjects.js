/**
 * useServiceProjects - Custom hook for managing project services
 * Extracted from serviceProjects.jsx for better separation of concerns
 * 
 * Handles:
 * - Services list fetching and pagination
 * - Add service modal state and form handling
 * - Service details modal state
 * - CRUD operations for services
 */

import { useState, useEffect } from "react";
import { ProjectService } from "../services/project.service";
import { IntegrationService } from "../services/integration.service";

// Initial form data for adding new service
const INITIAL_FORM_DATA = {
    service_type: "application",
    scm_type: "gitlab",
    infra_type: "database",
    infra_provider: "postgresql",
    name: "",
    description: "",
    status: "Active",
    gitlab_url: "",
    username: "",
    project_id: "",
    access_token: "",
    github_repo: "",
    github_token: "",
    host: "",
    port: "",
    health_check_url: "",
    integration_id: "",  // Global Integration ID
    cicd_type: "azure_devops",
    // Jenkins fields
    jenkins_url: "",
    jenkins_token: "",
    jenkins_username: "",
    jenkins_job: "",
};

const PAGE_SIZE = 5;

export const useServiceProjects = (projectId) => {
    // Project and services state
    const [projectName, setProjectName] = useState("");
    const [services, setServices] = useState([]);
    const [loading, setLoading] = useState(true);
    const [currentPage, setCurrentPage] = useState(1);

    // Add service modal state
    const [showModal, setShowModal] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submitError, setSubmitError] = useState(null);
    const [submitSuccess, setSubmitSuccess] = useState(false);
    const [formData, setFormData] = useState(INITIAL_FORM_DATA);

    // GitLab verification state
    const [verifying, setVerifying] = useState(false);
    const [projectVerified, setProjectVerified] = useState(false);
    const [verificationMessage, setVerificationMessage] = useState("");

    // GitHub verification state
    const [githubVerifying, setGithubVerifying] = useState(false);
    const [githubVerified, setGithubVerified] = useState(false);
    const [githubVerificationMessage, setGithubVerificationMessage] = useState("");

    // Bitbucket verification state
    const [bitbucketVerifying, setBitbucketVerifying] = useState(false);
    const [bitbucketVerified, setBitbucketVerified] = useState(false);
    const [bitbucketVerificationMessage, setBitbucketVerificationMessage] = useState("");

    // Azure DevOps verification state
    const [azureDevOpsVerifying, setAzureDevOpsVerifying] = useState(false);
    const [azureDevOpsVerified, setAzureDevOpsVerified] = useState(false);
    const [azureDevOpsVerificationMessage, setAzureDevOpsVerificationMessage] = useState("");

    // Details modal state
    const [selectedService, setSelectedService] = useState(null);
    const [showDetailsModal, setShowDetailsModal] = useState(false);
    const [loadingDetails, setLoadingDetails] = useState(false);
    const [detailsError, setDetailsError] = useState(null);

    // Fetch project data on mount
    useEffect(() => {
        const fetchProjectData = async () => {
            setLoading(true);
            try {
                const projectDetails = await ProjectService.GetProjectDetails(projectId);
                setProjectName(projectDetails.name);

                const servicesData = await ProjectService.GetProjectServices(projectId);
                setServices(servicesData);
            } catch (error) {
                console.error("Error fetching project data:", error);
            } finally {
                setLoading(false);
            }
        };

        if (projectId) {
            fetchProjectData();
        }
    }, [projectId]);

    // Pagination
    const totalPages = Math.ceil(services.length / PAGE_SIZE);
    const paginatedServices = services.slice(
        (currentPage - 1) * PAGE_SIZE,
        currentPage * PAGE_SIZE
    );

    const goToPage = (pageNumber) => {
        if (pageNumber < 1 || pageNumber > totalPages) return;
        setCurrentPage(pageNumber);
    };

    // Refresh services list
    const refreshServices = async () => {
        try {
            const data = await ProjectService.GetProjectServices(projectId);
            setServices(data);
        } catch (error) {
            console.error("Error refreshing services:", error);
        }
    };

    // GitLab verification - supports Global Integration
    const verifyGitLabProject = async () => {
        const token = localStorage.getItem("token");
        if (!token) {
            setSubmitError("You must be logged in to verify a project. Please log in again.");
            return false;
        }

        if (!formData.project_id) {
            setSubmitError("Project ID is required for verification");
            return false;
        }

        // If using global integration, we need to get credentials from there
        let accessToken = formData.access_token;
        let gitlabUrl = formData.gitlab_url;

        if (formData.integration_id) {
            try {
                const integrations = await IntegrationService.getAll();
                const integration = integrations.find(i => i.id === parseInt(formData.integration_id));
                if (integration) {
                    accessToken = integration.credentials?.token;
                    gitlabUrl = integration.base_url || 'https://gitlab.com';
                }
            } catch (err) {
                console.error("Failed to fetch integration credentials", err);
            }
        }

        if (!accessToken) {
            setSubmitError("Access Token is required for verification");
            return false;
        }

        setVerifying(true);
        setVerificationMessage("");
        setProjectVerified(false);

        try {
            const result = await ProjectService.VerifyGitLabProject({
                project_id: formData.project_id,
                access_token: accessToken,
                gitlab_url: gitlabUrl,
            });

            if (result.error) {
                setVerificationMessage(`Verification failed: ${result.error}`);
                setProjectVerified(false);
                return false;
            }

            setVerificationMessage("Project verified successfully!");
            setProjectVerified(true);
            return true;
        } catch (error) {
            console.error("Error verifying GitLab project:", error);
            setVerificationMessage("An error occurred during verification.");
            setProjectVerified(false);
            return false;
        } finally {
            setVerifying(false);
        }
    };

    // GitHub verification - supports Global Integration
    const verifyGitHubProject = async () => {
        const token = localStorage.getItem("token");
        if (!token) {
            setSubmitError("You must be logged in to verify a project. Please log in again.");
            return false;
        }

        if (!formData.github_repo) {
            setSubmitError("Repository is required for verification");
            return false;
        }

        // If using global integration, get credentials from there
        let githubToken = formData.github_token;

        if (formData.integration_id) {
            try {
                const integrations = await IntegrationService.getAll();
                const integration = integrations.find(i => i.id === parseInt(formData.integration_id));
                if (integration) {
                    githubToken = integration.credentials?.token;
                }
            } catch (err) {
                console.error("Failed to fetch integration credentials", err);
            }
        }

        if (!githubToken) {
            setSubmitError("Access Token is required for verification");
            return false;
        }

        setGithubVerifying(true);
        setGithubVerificationMessage("");
        setGithubVerified(false);

        try {
            const result = await ProjectService.VerifyGitHubProject({
                github_repo: formData.github_repo,
                github_token: githubToken,
            });

            if (result.error) {
                setGithubVerificationMessage(`Verification failed: ${result.error}`);
                setGithubVerified(false);
                return false;
            }

            setGithubVerificationMessage(`Repository verified: ${result.name || formData.github_repo}`);
            setGithubVerified(true);
            return true;
        } catch (error) {
            console.error("Error verifying GitHub project:", error);
            setGithubVerificationMessage("An error occurred during verification.");
            setGithubVerified(false);
            return false;
        } finally {
            setGithubVerifying(false);
        }
    };

    // Verify Bitbucket repository exists and token has access
    const verifyBitbucketProject = async () => {
        if (!formData.bitbucket_repo || !formData.bitbucket_token) {
            setBitbucketVerificationMessage("Repository and access token are required.");
            return false;
        }

        setBitbucketVerifying(true);
        setBitbucketVerificationMessage("");

        try {
            const result = await ProjectService.VerifyBitbucketProject(
                formData.bitbucket_repo,
                formData.bitbucket_token
            );

            if (result.error) {
                setBitbucketVerificationMessage(`Verification failed: ${result.error}`);
                setBitbucketVerified(false);
                return false;
            }

            setBitbucketVerificationMessage(`Repository verified: ${result.name || formData.bitbucket_repo}`);
            setBitbucketVerified(true);
            return true;
        } catch (error) {
            console.error("Error verifying Bitbucket project:", error);
            setBitbucketVerificationMessage("An error occurred during verification.");
            setBitbucketVerified(false);
            return false;
        } finally {
            setBitbucketVerifying(false);
        }
    };

    // Verify Azure DevOps project exists and PAT has access
    const verifyAzureDevOpsProject = async () => {
        if (!formData.azure_organization || !formData.azure_project || !formData.azure_pat) {
            setAzureDevOpsVerificationMessage("Organization, project, and PAT are required.");
            return false;
        }

        setAzureDevOpsVerifying(true);
        setAzureDevOpsVerificationMessage("");

        try {
            const result = await ProjectService.VerifyAzureDevOpsProject(
                formData.azure_organization,
                formData.azure_project,
                formData.azure_pat
            );

            if (result.error) {
                setAzureDevOpsVerificationMessage(`Verification failed: ${result.error}`);
                setAzureDevOpsVerified(false);
                return false;
            }

            setAzureDevOpsVerificationMessage(`Project verified: ${result.name || formData.azure_project}`);
            setAzureDevOpsVerified(true);
            return true;
        } catch (error) {
            console.error("Error verifying Azure DevOps project:", error);
            setAzureDevOpsVerificationMessage("An error occurred during verification.");
            setAzureDevOpsVerified(false);
            return false;
        } finally {
            setAzureDevOpsVerifying(false);
        }
    };

    // Modal handlers
    const handleOpenModal = () => {
        setShowModal(true);
        setSubmitError(null);
        setSubmitSuccess(false);
        setProjectVerified(false);
        setVerificationMessage("");
        // Reset all verification states
        setGithubVerified(false);
        setGithubVerificationMessage("");
        setBitbucketVerified(false);
        setBitbucketVerificationMessage("");
        setAzureDevOpsVerified(false);
        setAzureDevOpsVerificationMessage("");
        setFormData(INITIAL_FORM_DATA);
    };

    const handleCloseModal = () => {
        setShowModal(false);
        setSubmitError(null);
        setSubmitSuccess(false);
    };

    const handleChange = (e) => {
        const { name, value } = e.target;
        setFormData((prev) => ({ ...prev, [name]: value }));
        setSubmitError(null);
    };

    // Submit service
    const handleSubmit = async () => {
        const token = localStorage.getItem("token");
        if (!token) {
            setSubmitError("You must be logged in to perform this action. Please log in again.");
            return;
        }

        // Validation based on unified service types
        if (formData.service_type === "custom" && !formData.name) {
            setSubmitError("Service name is required");
            return;
        }

        if (formData.service_type === "infrastructure" && !formData.name) {
            setSubmitError("Service name is required");
            return;
        }

        // Application type validation
        if (formData.service_type === "application") {
            // SCM validation based on provider
            if (formData.scm_type === "gitlab") {
                if (!formData.project_id) {
                    setSubmitError("Project ID is required");
                    return;
                }
                if (!formData.integration_id) {
                    if (!formData.gitlab_url) {
                        setSubmitError("GitLab URL is required");
                        return;
                    }
                    if (!formData.access_token) {
                        setSubmitError("Access Token is required");
                        return;
                    }
                }
                if (!projectVerified) {
                    const isVerified = await verifyGitLabProject();
                    if (!isVerified) return;
                }
            } else if (formData.scm_type === "github") {
                if (!formData.github_repo) {
                    setSubmitError("GitHub Repository is required");
                    return;
                }
                if (!formData.integration_id && !formData.github_token) {
                    setSubmitError("GitHub Access Token is required");
                    return;
                }
                if (!githubVerified) {
                    const isVerified = await verifyGitHubProject();
                    if (!isVerified) return;
                }
            } else if (formData.scm_type === "bitbucket") {
                if (!formData.bitbucket_repo) {
                    setSubmitError("Bitbucket Repository is required");
                    return;
                }
                if (!bitbucketVerified) {
                    const isVerified = await verifyBitbucketProject();
                    if (!isVerified) return;
                }
            }
        }

        setIsSubmitting(true);
        setSubmitError(null);
        setSubmitSuccess(false);

        try {
            let result;
            let createdServiceId = null;

            // === UNIFIED SERVICE CREATION LOGIC ===
            if (formData.service_type === "application") {
                // Application service with SCM binding
                if (formData.scm_type === "gitlab") {
                    const gitlabPayload = {
                        service_type: "application",
                        status: "Active",
                        project_id: formData.project_id,
                        username: formData.username,
                        name: formData.name,
                    };
                    if (formData.integration_id) {
                        gitlabPayload.integration_id = formData.integration_id;
                    } else {
                        gitlabPayload.gitlab_url = formData.gitlab_url;
                        gitlabPayload.access_token = formData.access_token;
                    }
                    result = await ProjectService.AddGitLabProjectAsService(projectId, gitlabPayload);
                } else if (formData.scm_type === "github") {
                    const githubPayload = {
                        service_type: "application",
                        status: "Active",
                        github_repo: formData.github_repo,
                    };
                    if (formData.integration_id) {
                        githubPayload.integration_id = formData.integration_id;
                    } else {
                        githubPayload.github_token = formData.github_token;
                    }
                    result = await ProjectService.AddGitHubProjectAsService(projectId, githubPayload);
                } else if (formData.scm_type === "bitbucket") {
                    const bitbucketPayload = {
                        service_type: "application",
                        status: "Active",
                        bitbucket_repo: formData.bitbucket_repo,
                    };
                    if (formData.integration_id) {
                        bitbucketPayload.integration_id = formData.integration_id;
                    } else {
                        bitbucketPayload.bitbucket_token = formData.bitbucket_token;
                    }
                    result = await ProjectService.AddBitbucketProjectAsService(projectId, bitbucketPayload);
                }

                // Capture service ID for CI/CD binding
                if (result && result.id) {
                    createdServiceId = result.id;
                }
            } else if (formData.service_type === "infrastructure") {
                result = await ProjectService.AddInfraService(projectId, {
                    service_type: "infrastructure",
                    name: formData.name,
                    description: formData.description,
                    infra_type: formData.infra_type,
                    subtype: formData.infra_type,
                    provider: formData.infra_provider,
                    host: formData.host,
                    port: formData.port ? parseInt(formData.port) : null,
                    health_check_url: formData.health_check_url,
                    status: "Active",
                });
            } else {
                // Custom service
                result = await ProjectService.AddCustomService(projectId, {
                    service_type: "custom",
                    name: formData.name,
                    description: formData.description,
                    status: "Active",
                });
            }

            if (result?.error) {
                setSubmitError(result.error);
                return;
            }

            // === CI/CD BINDING CREATION ===
            // If add_cicd is enabled and we have a service, create the binding
            if (formData.add_cicd && formData.cicd_integration_id && createdServiceId) {
                try {
                    await ProjectService.addCICDBinding(createdServiceId, {
                        integration_id: parseInt(formData.cicd_integration_id),
                        binding_type: formData.cicd_type || "build",
                        pipeline_id: formData.cicd_pipeline_id || "",
                        pipeline_name: formData.cicd_pipeline_name || "",
                        auto_trigger: formData.cicd_auto_trigger !== false,
                    });
                    // Success — no log needed (the success case is
                    // covered by the outer flow's toast). FE-P2-01
                    // (audit 2026-09-05): removed orphan console.log
                    // that leaked into production browser devtools.
                } catch (cicdError) {
                    console.error("Failed to create CI/CD binding:", cicdError);
                    // Don't fail the whole operation, just log the error
                    // The service was created successfully
                }
            }

            setSubmitSuccess(true);
            setTimeout(() => {
                handleCloseModal();
                refreshServices();
            }, 1500);
        } catch (error) {
            console.error("Error details:", error);
            let errorMessage = "Error creating service";

            if (error.response) {
                if (error.response.status === 401 || error.response.status === 403) {
                    errorMessage = "Authentication failed. Please log in again.";
                } else if (error.response.data?.error) {
                    errorMessage = error.response.data.error;
                } else if (error.response.data?.detail) {
                    errorMessage = error.response.data.detail;
                }
            }

            setSubmitError(errorMessage);
        } finally {
            setIsSubmitting(false);
        }
    };

    // Details modal handlers
    // Service details (scm_binding, cicd_bindings) are included in the
    // backend serializer response — no extra fetch needed.
    const handleViewDetails = (service) => {
        setSelectedService(service);
        setShowDetailsModal(true);
        setDetailsError(null);
    };

    const handleCloseDetailsModal = () => {
        setShowDetailsModal(false);
        setSelectedService(null);
        setDetailsError(null);
    };

    // Delete service
    const handleDelete = async (serviceId) => {
        if (window.confirm("Are you sure you want to delete this service?")) {
            try {
                await ProjectService.DeleteProjectService(serviceId);
                await refreshServices();
            } catch (error) {
                console.error("Error deleting service:", error);
                alert("Failed to delete service. Please try again.");
            }
        }
    };

    return {
        // Project data
        projectName,
        services: paginatedServices,
        loading,

        // Pagination
        currentPage,
        totalPages,
        goToPage,

        // Add service modal
        showModal,
        formData,
        setFormData,
        isSubmitting,
        submitError,
        submitSuccess,
        handleOpenModal,
        handleCloseModal,
        handleChange,
        handleSubmit,

        // GitLab verification
        verifying,
        projectVerified,
        verificationMessage,
        verifyGitLabProject,

        // GitHub verification
        githubVerifying,
        githubVerified,
        githubVerificationMessage,
        verifyGitHubProject,

        // Bitbucket verification
        bitbucketVerifying,
        bitbucketVerified,
        bitbucketVerificationMessage,
        verifyBitbucketProject,

        // Azure DevOps verification
        azureDevOpsVerifying,
        azureDevOpsVerified,
        azureDevOpsVerificationMessage,
        verifyAzureDevOpsProject,

        // Details modal
        selectedService,
        showDetailsModal,
        loadingDetails,
        detailsError,
        handleViewDetails,
        handleCloseDetailsModal,

        // Actions
        handleDelete,
        refreshServices,
    };
};

export default useServiceProjects;
