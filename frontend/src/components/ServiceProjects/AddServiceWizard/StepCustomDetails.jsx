/**
 * StepCustomDetails - Step 2c: Custom service details
 * For Custom service type - simple name and description entry
 */

import React from "react";
import { Form } from "react-bootstrap";

const StepCustomDetails = ({ formData, updateFormData }) => {
    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">Custom Service Details</h5>
            <p className="wizard-step-subtitle">
                Enter details for your custom or legacy service.
            </p>

            {/* Service Name */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-customdetails-1">Service Name *</label>
                <Form.Control id="wizard-customdetails-1"
                    type="text"
                    placeholder="e.g., Legacy Payment Gateway"
                    value={formData.serviceName || ""}
                    onChange={(e) => updateFormData({ serviceName: e.target.value })}
                    className="rounded-3"
                    required
                />
            </div>

            {/* Description */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-customdetails-2">Description</label>
                <Form.Control id="wizard-customdetails-2"
                    as="textarea"
                    rows={3}
                    placeholder="What this service does and key dependencies — used by AI for analysis"
                    value={formData.description || ""}
                    onChange={(e) => updateFormData({ description: e.target.value })}
                    className="rounded-3"
                    maxLength={500}
                />
                <div className="text-muted small text-end mt-1">
                    {(formData.description || '').length}/500
                </div>
            </div>
        </div>
    );
};

export default StepCustomDetails;
