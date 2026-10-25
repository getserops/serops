/**
 * StepInfraDetails - Step 2b: Infrastructure service details
 * For Infrastructure service type - select type and enter details
 */

import React from "react";
import { Form } from "react-bootstrap";
import { FaDatabase, FaMemory, FaStream, FaCogs } from "react-icons/fa";

const infraTypes = [
    { id: "database", label: "Database", icon: FaDatabase },
    { id: "cache", label: "Cache", icon: FaMemory },
    { id: "queue", label: "Queue", icon: FaStream },
    { id: "other", label: "Other", icon: FaCogs },
];

const infraProviders = {
    database: ["PostgreSQL", "MySQL", "MongoDB", "Redis", "Elasticsearch"],
    cache: ["Redis", "Memcached", "Hazelcast"],
    queue: ["RabbitMQ", "Kafka", "SQS", "Redis"],
    other: ["Custom"],
};

const StepInfraDetails = ({ formData, updateFormData }) => {
    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">Infrastructure Details</h5>
            <p className="wizard-step-subtitle">
                Configure your infrastructure service.
            </p>

            {/* Infrastructure Type */}
            <div className="wizard-form-section">
                <span className="wizard-form-label d-block" id="wizard-infra-type">Type</span>
                <div className="infra-type-pills" role="group" aria-labelledby="wizard-infra-type">
                    {infraTypes.map((type) => {
                        const Icon = type.icon;
                        const isActive = formData.infraType === type.id;

                        return (
                            <button
                                key={type.id}
                                type="button"
                                aria-pressed={isActive}
                                className={`infra-pill ${isActive ? 'active' : ''}`}
                                onClick={() => updateFormData({ infraType: type.id, infraProvider: '' })}
                            >
                                <Icon className="me-2" />
                                {type.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {/* Provider Selection */}
            {formData.infraType && (
                <div className="wizard-form-section">
                    <label className="wizard-form-label" htmlFor="wizard-infradetails-1">Provider</label>
                    <Form.Select id="wizard-infradetails-1"
                        value={formData.infraProvider || ""}
                        onChange={(e) => updateFormData({ infraProvider: e.target.value })}
                        className="rounded-3"
                    >
                        <option value="">Select provider...</option>
                        {infraProviders[formData.infraType]?.map(provider => (
                            <option key={provider} value={provider.toLowerCase()}>
                                {provider}
                            </option>
                        ))}
                    </Form.Select>
                </div>
            )}

            {/* Service Name */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-infradetails-2">Service Name *</label>
                <Form.Control id="wizard-infradetails-2"
                    type="text"
                    placeholder="e.g., User Database, Redis Cache"
                    value={formData.serviceName || ""}
                    onChange={(e) => updateFormData({ serviceName: e.target.value })}
                    className="rounded-3"
                    required
                />
            </div>

            {/* Description */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-infradetails-3">Description (optional)</label>
                <Form.Control id="wizard-infradetails-3"
                    as="textarea"
                    rows={2}
                    placeholder="Role and connections — used by AI for analysis"
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

export default StepInfraDetails;
