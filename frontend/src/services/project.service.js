import axios from "axios";
import { describeRequestError } from "../utils/apiError";

const BACKEND_HOST = import.meta.env.VITE_BASE_URL;
const API_BASE_URL = BACKEND_HOST;
const PROVIDERS_API_URL = BACKEND_HOST + "/providers";

// Debug helper function
const checkAndLogToken = () => {
  const token = localStorage.getItem("token");
  if (!token) {
    console.error("ERROR: No authentication token found in localStorage!");
    return null;
  } else {
    return token;
  }
};

const getAuthHeader = () => {
  const token = checkAndLogToken();
  if (!token) {
    console.error("Cannot create auth header without a token");
  }
  return {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Token ${token}`,
    },
  };
};

export const ProjectService = {
  // Project CRUD operations
  CreateProject: async (projectData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/`,
        projectData,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error("Error creating project:", error);
      if (error.response && error.response.data) {
        return {
          error: error.response.data.error || "Failed to create project",
        };
      }
      throw error;
    }
  },

  GetProjects: async () => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/projects/`,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error("Error fetching projects:", error);
      throw error;
    }
  },

  GetProjectDetails: async (projectId) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/projects/${projectId}/`,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error fetching project ${projectId}:`, error);
      throw error;
    }
  },

  UpdateProject: async (projectId, projectData) => {
    try {
      const response = await axios.put(
        `${API_BASE_URL}/projects/${projectId}/`,
        projectData,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error updating project ${projectId}:`, error);
      throw error;
    }
  },

  DeleteProject: async (projectId) => {
    try {
      await axios.delete(
        `${API_BASE_URL}/projects/${projectId}/`,
        getAuthHeader()
      );
      return { success: true };
    } catch (error) {
      console.error(`Error deleting project ${projectId}:`, error);
      throw error;
    }
  },

  // Service operations - adding services to projects
  AddServiceToProject: async (projectId, serviceData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        serviceData,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error adding service to project ${projectId}:`, error);
      if (error.response && error.response.data) {
        return {
          error:
            error.response.data.error || "Failed to add service to project",
        };
      }
      throw error;
    }
  },

  GetProjectServices: async (projectId) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        getAuthHeader()
      );

      const services = response.data;

      if (!services || services.length === 0) {
        return [];
      }

      // Return services with display defaults — backend includes
      // scm_binding, cicd_bindings, and other provider-agnostic fields
      return services.map((service) => ({
        ...service,
        name: service.name || service.scm_binding?.repository_name || `Service #${service.id}`,
        status: service.status || "Active",
        created_at: service.created_at || new Date().toISOString(),
      }));
    } catch (error) {
      console.error(`Error fetching services for project ${projectId}:`, error);
      throw error;
    }
  },

  DeleteProjectService: async (serviceId) => {
    try {
      await axios.delete(
        `${API_BASE_URL}/projects/services/${serviceId}/`,
        getAuthHeader()
      );
      return { success: true };
    } catch (error) {
      console.error(`Error deleting service ${serviceId}:`, error);
      throw error;
    }
  },

  // GitLab related operations
  VerifyGitLabProject: async (verificationData) => {
    try {
      // Make sure we have a token
      const authHeader = getAuthHeader();

      // Based on your backend, we'll simulate verification by checking if the provided
      // project_id and access_token are valid with GitLab's API
      const response = await axios.post(
        `${PROVIDERS_API_URL}/verify-project/`,
        {
          project_id: verificationData.project_id,
          access_token: verificationData.access_token,
        },
        authHeader
      );

      return {
        verified: true,
        details: response.data,
      };
    } catch (error) {
      console.error("Error verifying GitLab project:", error);

      if (error.response) {
        let errorMessage = "Failed to verify GitLab project";

        if (error.response.data && error.response.data.error) {
          errorMessage = error.response.data.error;
        } else if (typeof error.response.data === "string") {
          errorMessage = error.response.data;
        }

        return {
          error: errorMessage,
          verified: false,
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error during verification",
        verified: false,
      };
    }
  },

  // GitHub verification - verify repo exists and token works
  VerifyGitHubProject: async (verificationData) => {
    try {
      const authHeader = getAuthHeader();

      // Call backend to verify GitHub project
      const response = await axios.post(
        `${PROVIDERS_API_URL}/verify-github/`,
        {
          github_repo: verificationData.github_repo,
          github_token: verificationData.github_token,
        },
        authHeader
      );

      return {
        verified: true,
        name: response.data.name,
        full_name: response.data.full_name,
        description: response.data.description,
      };
    } catch (error) {
      console.error("Error verifying GitHub project:", error);

      if (error.response) {
        let errorMessage = "Failed to verify GitHub repository";

        if (error.response.data && error.response.data.error) {
          errorMessage = error.response.data.error;
        } else if (typeof error.response.data === "string") {
          errorMessage = error.response.data;
        }

        return {
          error: errorMessage,
          verified: false,
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error during verification",
        verified: false,
      };
    }
  },

  // Add GitHub project as a service
  AddGitHubProjectAsService: async (projectId, githubData) => {
    try {
      const authHeader = getAuthHeader();

      // Create GitHub service via backend
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "application",
          name: githubData.github_repo,
          description: `GitHub repository: ${githubData.github_repo}`,
          provider_config: {
            repo: githubData.github_repo,
            token: githubData.github_token,
          },
        },
        authHeader
      );

      return {
        success: true,
        data: response.data,
      };
    } catch (error) {
      console.error(`Error adding GitHub project as service:`, error);

      if (error.response) {
        return {
          error: error.response.data?.error || "Failed to add GitHub service",
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error",
      };
    }
  },

  /**
   * Add Bitbucket repository as a service to a project
   */
  AddBitbucketProjectAsService: async (projectId, bitbucketData) => {
    try {
      const authHeader = getAuthHeader();

      // Create Bitbucket service via backend
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "application",
          name: bitbucketData.name || bitbucketData.bitbucket_repo,
          description: `Bitbucket repository: ${bitbucketData.bitbucket_repo}`,
          provider_config: {
            repo: bitbucketData.bitbucket_repo,
            integration_id: bitbucketData.integration_id,
          },
        },
        authHeader
      );

      return {
        success: true,
        id: response.data.id,
        data: response.data,
      };
    } catch (error) {
      console.error(`Error adding Bitbucket project as service:`, error);

      if (error.response) {
        return {
          error: error.response.data?.error || "Failed to add Bitbucket service",
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error",
      };
    }
  },

  /**
   * Verify Bitbucket repository access
   */
  VerifyBitbucketProject: async (bitbucketRepo, bitbucketToken) => {
    try {
      const response = await axios.post(
        `${PROVIDERS_API_URL}/verify-bitbucket/`,
        {
          bitbucket_repo: bitbucketRepo,
          bitbucket_token: bitbucketToken,
        },
        {
          headers: {
            "Content-Type": "application/json",
            Authorization: `Token ${localStorage.getItem("token")}`,
          },
        }
      );

      return response.data;
    } catch (error) {
      console.error("Error verifying Bitbucket project:", error);

      if (error.response) {
        return {
          exists: false,
          error: error.response.data?.error || "Failed to verify Bitbucket repository",
        };
      }

      return {
        exists: false,
        error: error.message || "Connection error",
      };
    }
  },

  /**
   * Verify Azure DevOps project access
   */
  VerifyAzureDevOpsProject: async (organization, project, pat) => {
    try {
      const response = await axios.post(
        `${PROVIDERS_API_URL}/verify-azure-devops/`,
        {
          organization: organization,
          project: project,
          pat: pat,
        },
        {
          headers: {
            "Content-Type": "application/json",
            Authorization: `Token ${localStorage.getItem("token")}`,
          },
        }
      );

      return response.data;
    } catch (error) {
      console.error("Error verifying Azure DevOps project:", error);

      if (error.response) {
        return {
          exists: false,
          error: error.response.data?.error || "Failed to verify Azure DevOps project",
        };
      }

      return {
        exists: false,
        error: error.message || "Connection error",
      };
    }
  },

  GetGitLabProjectDetails: async (gitlabProjectId) => {
    try {
      // Get authentication headers
      const authHeader = getAuthHeader();

      // Using the exact endpoint format from your backend
      const response = await axios({
        method: "get",
        url: `${PROVIDERS_API_URL}/${gitlabProjectId}/`,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Token ${localStorage.getItem("token")}`,
        },
      });

      // The backend returns the GitLab project details directly
      const gitlabProject = response.data;

      return {
        success: true,
        data: {
          id: gitlabProject.id,
          name: gitlabProject.name || "",
          gitlab_url: gitlabProject.gitlab_url,
          username: gitlabProject.username,
          project_id: gitlabProject.project_id,
          webhook: gitlabProject.webhook,
          // We're not returning the access_token for security reasons
        },
      };
    } catch (error) {
      console.error(
        `Error fetching GitLab project details for ID ${gitlabProjectId}:`,
        error
      );

      if (error.response) {
        return {
          error:
            error.response.data?.detail ||
            error.response.data?.error ||
            `Failed to fetch GitLab project details. Status: ${error.response.status}`,
          status: error.response.status,
        };
      }

      return {
        error:
          error.message ||
          "Connection error while fetching GitLab project details",
      };
    }
  },

  AddGitLabProjectAsService: async (projectId, gitlabData) => {
    try {
      // Get authentication headers
      const authHeader = getAuthHeader();

      // Step 1: Create/register the GitLab project in our system
      // If using global integration, pass integration_id; otherwise pass manual credentials
      const gitlabPayload = {
        project_id: gitlabData.project_id,
      };

      if (gitlabData.integration_id) {
        gitlabPayload.integration_id = gitlabData.integration_id;
      } else {
        gitlabPayload.gitlab_url = gitlabData.gitlab_url;
        gitlabPayload.username = gitlabData.username;
        gitlabPayload.access_token = gitlabData.access_token;
      }


      // Make the request with explicit authorization header
      const gitlabResponse = await axios({
        method: "post",
        url: `${PROVIDERS_API_URL}/`,
        data: gitlabPayload,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Token ${localStorage.getItem("token")}`,
        },
      });

      // Extract the created GitLab project ID
      const gitlabProjectId = gitlabResponse.data.project.id;


      // Step 2: Create a service in the current project that links to this GitLab project
      // Use user-entered name if provided, otherwise fallback to GitLab project name
      const serviceName = gitlabData.name || gitlabResponse.data.project?.name || `GitLab Project ${gitlabData.project_id}`;
      const servicePayload = {
        name: serviceName,
        service_type: "application",
        description: `GitLab project at ${gitlabData.gitlab_url || gitlabData.project_id
          }`,
        gitlab_project: gitlabProjectId, // Link to the GitLab project we just created
      };

      // Make the request with explicit authorization header
      const serviceResponse = await axios({
        method: "post",
        url: `${API_BASE_URL}/projects/${projectId}/services/`,
        data: servicePayload,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Token ${localStorage.getItem("token")}`,
        },
      });
      // Return the combined result
      return {
        success: true,
        data: {
          service: serviceResponse.data,
          gitlabProject: gitlabResponse.data,
        },
      };
    } catch (error) {
      console.error(
        `Error adding GitLab project as service to project ${projectId}:`,
        error
      );

      // Identify which step failed
      let step = "unknown";
      if (error.message && error.message.includes("gitlabResponse")) {
        step = "registering GitLab project";
      } else if (error.message && error.message.includes("serviceResponse")) {
        step = "creating service";
      }

      // Detailed error handling
      if (error.response) {
        // The request was made and the server responded with a status code
        // that falls out of the range of 2xx
        console.error("Response data:", error.response.data);
        console.error("Response status:", error.response.status);

        let errorMessage = `Failed while ${step}: `;

        // Extract specific error message if available
        if (error.response.data && error.response.data.detail) {
          errorMessage += error.response.data.detail;
        } else if (error.response.data && error.response.data.error) {
          errorMessage += error.response.data.error;
        } else if (typeof error.response.data === "string") {
          errorMessage += error.response.data;
        } else {
          errorMessage += `Server returned ${error.response.status}`;
        }

        return {
          error: errorMessage,
          status: error.response.status,
          step: step,
        };
      } else if (error.request) {
        // The request was made but no response was received
        return {
          error: `No response received from server while ${step}. Please check your network connection.`,
          step: step,
        };
      } else {
        // Something happened in setting up the request that triggered an Error
        return {
          error: `Error while ${step}: ${error.message || "Unknown error occurred"
            }`,
          step: step,
        };
      }
    }
  },

  // Azure DevOps Service Method
  AddAzureDevOpsProjectAsService: async (projectId, azureData) => {
    try {
      const authHeader = getAuthHeader();

      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "application",
          name: `${azureData.azure_project} (${azureData.azure_organization})`,
          description: `Azure DevOps Pipeline: ${azureData.azure_organization}/${azureData.azure_project}`,
          status: "Active",
          organization: azureData.azure_organization,
          project: azureData.azure_project,
          pat: azureData.azure_pat
        },
        authHeader
      );

      return {
        success: true,
        data: response.data,
      };
    } catch (error) {
      console.error(`Error adding Azure DevOps service to project ${projectId}:`, error);

      if (error.response) {
        return {
          error: error.response.data?.error || "Failed to add Azure DevOps service",
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error",
      };
    }
  },

  // Jenkins Service Method
  AddJenkinsAsService: async (projectId, jenkinsData) => {
    try {
      const authHeader = getAuthHeader();

      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "application",
          name: jenkinsData.name || "Jenkins Pipeline",
          description: `Jenkins CI/CD: ${jenkinsData.jenkins_url}`,
          status: "Active",
          provider_config: {
            url: jenkinsData.jenkins_url,
            token: jenkinsData.jenkins_token,
            username: jenkinsData.jenkins_username || "",
            job: jenkinsData.jenkins_job || "",
          },
        },
        authHeader
      );

      return {
        success: true,
        data: response.data,
      };
    } catch (error) {
      console.error(`Error adding Jenkins service to project ${projectId}:`, error);

      if (error.response) {
        return {
          error: error.response.data?.error || "Failed to add Jenkins service",
          status: error.response.status,
        };
      }

      return {
        error: error.message || "Connection error",
      };
    }
  },

  // Custom Services Methods
  AddCustomService: async (projectId, serviceData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/custom-services/`,
        {
          name: serviceData.name,
          description: serviceData.description,
          service_type: "custom",
          status: serviceData.status || "Active",
        },
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(
        `Erreur lors de l'ajout du service personnalisé au projet ${projectId} :`,
        error
      );
      if (error.response?.data) {
        return {
          error:
            error.response.data.error ||
            "Échec de l'ajout du service personnalisé",
        };
      }
      throw error;
    }
  },

  // An application service with no repository connected (B4).
  AddApplicationService: async (projectId, serviceData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "application",
          name: serviceData.name,
          description: serviceData.description || "",
          status: "Active",
        },
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      return { error: describeRequestError(error, "Failed to create service") };
    }
  },

  // Infrastructure Services Methods
  AddInfraService: async (projectId, serviceData) => {
    try {
      // Use the same endpoint as other services so they appear in the services list
      const response = await axios.post(
        `${API_BASE_URL}/projects/${projectId}/services/`,
        {
          service_type: "infrastructure",  // Proper type for infrastructure services
          name: serviceData.name,
          description: serviceData.description || "",
          status: "Active",
          provider_config: {
            infra_type: serviceData.infra_type,
            provider: serviceData.provider,
            host: serviceData.host || "",
            port: serviceData.port || null,
            health_check_url: serviceData.health_check_url || "",
          },
        },
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(
        `Error adding infrastructure service to project ${projectId}:`,
        error
      );
      if (error.response?.data) {
        return {
          error:
            error.response.data.error ||
            error.response.data.detail ||
            "Failed to add infrastructure service",
        };
      }
      throw error;
    }
  },

  // Binding Operations
  SyncSCMBinding: async (bindingId) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/scm-bindings/${bindingId}/sync/`,
        {},
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error syncing SCM binding ${bindingId}:`, error);
      throw error;
    }
  },

  SetupSCMWebhook: async (bindingId) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/scm-bindings/${bindingId}/setup-webhook/`,
        {},
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error configuring webhook for binding ${bindingId}:`, error);
      throw error;
    }
  },

  // CI/CD Binding Operations
  addCICDBinding: async (serviceId, bindingData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/projects/cicd-bindings/`,
        {
          project_service: serviceId,
          integration: bindingData.integration_id,
          binding_type: bindingData.binding_type,
          pipeline_id: bindingData.pipeline_id,
          pipeline_name: bindingData.pipeline_name || '',
          auto_trigger: bindingData.auto_trigger ?? true,
        },
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error adding CI/CD binding for service ${serviceId}:`, error);
      throw error;
    }
  },

  deleteCICDBinding: async (bindingId) => {
    try {
      const response = await axios.delete(
        `${API_BASE_URL}/projects/cicd-bindings/${bindingId}/`,
        getAuthHeader()
      );
      return response.data;
    } catch (error) {
      console.error(`Error deleting CI/CD binding ${bindingId}:`, error);
      throw error;
    }
  },
};
