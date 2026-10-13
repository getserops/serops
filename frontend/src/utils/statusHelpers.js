/**
 * Status badge utility functions for service/project status display
 */

import React from "react";

/**
 * Returns a styled badge component based on the status value
 * @param {string} status - The status value (active, inactive, etc.)
 * @returns {JSX.Element} Badge component
 */
export const getStatusBadge = (status) => {
    switch (status) {
        case "active":
        case "Active":
            return (
                <span className="badge bg-success bg-opacity-25 text-success px-3 py-2 rounded-pill">
                    Active
                </span>
            );
        case "inactive":
        case "Inactive":
            return (
                <span className="badge bg-danger bg-opacity-25 text-danger px-3 py-2 rounded-pill">
                    Inactive
                </span>
            );
        default:
            return <span className="badge bg-secondary">Unknown</span>;
    }
};

/**
 * Returns status color for various uses (charts, indicators, etc.)
 * @param {string} status - The status value
 * @returns {string} Color code
 */
export const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
        case "active":
            return "#28a745"; // green
        case "inactive":
            return "#dc3545"; // red
        case "pending":
            return "#ffc107"; // yellow
        default:
            return "#6c757d"; // gray
    }
};
