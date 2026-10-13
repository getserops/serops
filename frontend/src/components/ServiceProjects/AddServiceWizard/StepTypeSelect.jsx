/**
 * StepTypeSelect - Step 1: Choose service type
 * User selects between Application, Infrastructure, or Custom
 */

import React from "react";
import { FaCode, FaServer, FaEdit, FaChevronRight } from "react-icons/fa";

const serviceTypes = [
    {
        id: "application",
        icon: FaCode,
        title: "Application",
        description: "Microservices, APIs, backends, frontends with code repository and CI/CD connections",
        color: "#0d6efd"
    },
    {
        id: "infrastructure",
        icon: FaServer,
        title: "Infrastructure",
        description: "Databases, caches, message queues, and other non-code services",
        color: "#198754"
    },
    {
        id: "custom",
        icon: FaEdit,
        title: "Custom",
        description: "Manual service entry for legacy systems or external services",
        color: "#6c757d"
    }
];

const StepTypeSelect = ({ selectedType, onTypeSelect }) => {
    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">What type of service are you adding?</h5>

            <div className="type-selection-grid">
                {serviceTypes.map((type) => {
                    const Icon = type.icon;
                    const isSelected = selectedType === type.id;

                    return (
                        <div
                            key={type.id}
                            className={`type-card ${isSelected ? 'selected' : ''}`}
                            onClick={() => onTypeSelect(type.id)}
                        >
                            <div
                                className="type-card-icon"
                                style={{
                                    background: isSelected ? type.color : undefined,
                                    color: isSelected ? 'white' : type.color
                                }}
                            >
                                <Icon />
                            </div>
                            <div className="type-card-content">
                                <div className="type-card-title">{type.title}</div>
                                <p className="type-card-description">{type.description}</p>
                            </div>
                            <div className="type-card-arrow">
                                <FaChevronRight />
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default StepTypeSelect;
