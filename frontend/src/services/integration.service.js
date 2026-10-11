import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_BASE_URL + "/providers";

const getAuthHeader = () => {
    const token = localStorage.getItem("token");
    return {
        headers: {
            "Content-Type": "application/json",
            Authorization: `Token ${token}`,
        },
    };
};

export const IntegrationService = {
    getAll: async () => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/integrations/`,
                getAuthHeader()
            );
            return response.data;
        } catch (error) {
            console.error("Error fetching integrations:", error);
            throw error;
        }
    },

    create: async (data) => {
        try {
            const response = await axios.post(
                `${API_BASE_URL}/integrations/`,
                data,
                getAuthHeader()
            );
            return response.data;
        } catch (error) {
            console.error("Error creating integration:", error);
            throw error;
        }
    },

    update: async (id, data) => {
        try {
            const response = await axios.patch(
                `${API_BASE_URL}/integrations/${id}/`,
                data,
                getAuthHeader()
            );
            return response.data;
        } catch (error) {
            console.error(`Error updating integration ${id}:`, error);
            throw error;
        }
    },

    delete: async (id) => {
        try {
            await axios.delete(
                `${API_BASE_URL}/integrations/${id}/`,
                getAuthHeader()
            );
            return { success: true };
        } catch (error) {
            console.error(`Error deleting integration ${id}:`, error);
            throw error;
        }
    },

    getRepos: async (id, params = {}) => {
        try {
            const response = await axios.get(
                `${API_BASE_URL}/integrations/${id}/repos/`,
                {
                    ...getAuthHeader(),
                    params
                }
            );
            return response.data;
        } catch (error) {
            console.error(`Error fetching repos for integration ${id}:`, error);
            throw error;
        }
    },
};
