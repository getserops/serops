// services/issuesStats.service.js
import axios from "axios";

const AUTH_HOST = import.meta.env.VITE_BASE_URL;
const API_URL = AUTH_HOST + "/data/issue-stats/";

// Helper to get auth headers
const getAuthHeaders = () => {
  const token = localStorage.getItem("token");
  return token ? { Authorization: `Token ${token}` } : {};
};

class IssueStatsService {
  static async getIssueStats() {
    try {
      const response = await axios.get(API_URL, {
        headers: getAuthHeaders()
      });

      if (!response.data) {
        throw new Error("Invalid data format from API");
      }

      const { statistics, unknown_severities } = response.data;

      if (!statistics) {
        throw new Error("Missing statistics in API response");
      }

      const { critical, warning, info } = statistics;

      // Build the base array with known severities
      let result = [
        {
          name: "CRITICAL",
          value: critical.count,
          color: "#e53935", // Deep red
          percentage: critical.percentage || 0,
        },
        {
          name: "WARNING",
          value: warning.count,
          color: "#fb8c00", // Orange
          percentage: warning.percentage || 0,
        },
        {
          name: "INFO",
          value: info.count,
          color: "#1e88e5", // Blue
          percentage: info.percentage || 0,
        },
      ];

      // Add unknown severities if they exist
      if (unknown_severities) {
        // Add HIGH severity if it exists
        if (unknown_severities.HIGH) {
          result.push({
            name: "HIGH",
            value: unknown_severities.HIGH.count,
            color: "#d81b60", // Red-pink
            percentage: unknown_severities.HIGH.percentage || 0,
          });
        }

        // Add MEDIUM severity if it exists
        if (unknown_severities.MEDIUM) {
          result.push({
            name: "MEDIUM",
            value: unknown_severities.MEDIUM.count,
            color: "#ffb300", // Amber
            percentage: unknown_severities.MEDIUM.percentage || 0,
          });
        }

        // Add LOW severity if it exists
        if (unknown_severities.LOW) {
          result.push({
            name: "LOW",
            value: unknown_severities.LOW.count,
            color: "#43a047", // Green
            percentage: unknown_severities.LOW.percentage || 0,
          });
        }
      }

      // Calculate percentages if they're not provided
      const total = result.reduce((sum, item) => sum + item.value, 0);

      if (total > 0) {
        result = result.map((item) => ({
          ...item,
          percentage: item.percentage || Math.round((item.value / total) * 100),
        }));
      }

      return result;
    } catch (error) {
      console.error("Error fetching issue stats:", error);

      // Return default data structure with all possible severities
      return [
        { name: "CRITICAL", value: 0, color: "#e53935", percentage: 0 },
        { name: "HIGH", value: 0, color: "#d81b60", percentage: 0 },
        { name: "MEDIUM", value: 0, color: "#ffb300", percentage: 0 },
        { name: "WARNING", value: 0, color: "#fb8c00", percentage: 0 },
        { name: "LOW", value: 0, color: "#43a047", percentage: 0 },
        { name: "INFO", value: 0, color: "#1e88e5", percentage: 0 },
      ];
    }
  }
}

export default IssueStatsService;
