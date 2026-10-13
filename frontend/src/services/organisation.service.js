import axios from "axios";

const AUTH_HOST = import.meta.env.VITE_BASE_URL;
const API_BASE_URL = AUTH_HOST + "/organisation";

// Helper to get auth headers
const getAuthHeaders = () => {
  const token = localStorage.getItem("token");
  return {
    headers: {
      Authorization: `Token ${token}`,
    },
  };
};

export const OrganisationService = {
  // Get current user's organisation info
  getOrganisationInfo: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/info/`, getAuthHeaders());
      return response.data;
    } catch (error) {
      console.error("Error fetching organisation info:", error);
      throw error;
    }
  },

  // Update organisation info (language, website)
  updateOrganisationInfo: async (data) => {
    try {
      const response = await axios.put(`${API_BASE_URL}/info/`, data, getAuthHeaders());
      return response.data;
    } catch (error) {
      console.error("Error updating organisation info:", error);
      throw error;
    }
  },

  // Upload organisation logo
  uploadLogo: async (file) => {
    try {
      const formData = new FormData();
      formData.append('logo', file);

      const token = localStorage.getItem("token");
      const response = await axios.put(`${API_BASE_URL}/info/`, formData, {
        headers: {
          Authorization: `Token ${token}`,
          'Content-Type': 'multipart/form-data',
        },
      });
      return response.data;
    } catch (error) {
      console.error("Error uploading logo:", error);
      throw error;
    }
  },

  getAllOrganisations: async () => {
    try {
      const response = await axios.get(`${API_BASE_URL}/list/`, getAuthHeaders());
      return response.data.organisations;
    } catch (error) {
      console.error("Error fetching organisations:", error);
      throw error;
    }
  },

  createOrganisation: async (organisationData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/create/`,
        organisationData,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error creating organisation:", error);
      throw error;
    }
  },

  updateOrganisation: async (id, organisationData) => {
    try {
      const response = await axios.put(
        `${API_BASE_URL}/update/${id}/`,
        organisationData,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error updating organisation:", error);
      throw error;
    }
  },

  deleteOrganisation: async (id) => {
    try {
      await axios.delete(`${API_BASE_URL}/delete/${id}/`, getAuthHeaders());
    } catch (error) {
      console.error("Error deleting organisation:", error);
      throw error;
    }
  },

  // Team Management Methods
  getTeamMembers: async (page = 1, perPage = 50) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/team/?page=${page}&per_page=${perPage}`,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error fetching team members:", error);
      throw error;
    }
  },

  inviteTeamMember: async (userData) => {
    try {
      const response = await axios.post(
        `${API_BASE_URL}/team/`,
        userData,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error inviting team member:", error);
      throw error;
    }
  },

  getTeamMember: async (id) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/member/${id}/`,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error fetching team member:", error);
      throw error;
    }
  },

  updateTeamMember: async (id, userData) => {
    try {
      const response = await axios.put(
        `${API_BASE_URL}/member/${id}/`,
        userData,
        getAuthHeaders()
      );
      return response.data;
    } catch (error) {
      console.error("Error updating team member:", error);
      throw error;
    }
  },

  deleteTeamMember: async (id) => {
    try {
      await axios.delete(
        `${API_BASE_URL}/member/${id}/`,
        getAuthHeaders()
      );
    } catch (error) {
      console.error("Error deleting team member:", error);
      throw error;
    }
  },
};
