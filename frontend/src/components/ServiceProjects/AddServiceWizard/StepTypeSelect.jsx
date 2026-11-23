/**
 * StepTypeSelect - Step 1: Choose service type
 * User selects between Application, Infrastructure, or Custom
 */

import React from "react";
import { FaCode, FaServer, FaEdit, FaChevronRight } from "react-icons/fa";
import { useTranslation } from "react-i18next";

const serviceTypes = [
    {
        id: "application",
        icon: FaCode,
        titleKey: "services.typeApplication",
        descriptionKey: "addServiceWizard.typeSelect.applicationDesc",
        color: "#0d6efd"
    },
    {
        id: "infrastructure",
        icon: FaServer,
        titleKey: "addService.infrastructure",
        descriptionKey: "addServiceWizard.typeSelect.infrastructureDesc",
        color: "#198754"
    },
    {
        id: "custom",
        icon: FaEdit,
        titleKey: "addService.custom",
        descriptionKey: "addServiceWizard.typeSelect.customDesc",
        color: "#6c757d"
    }
];

const StepTypeSelect = ({ selectedType, onTypeSelect }) => {
    const { t } = useTranslation();
    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">{t('addServiceWizard.typeSelect.title')}</h5>

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
                                <div className="type-card-title">{t(type.titleKey)}</div>
                                <p className="type-card-description">{t(type.descriptionKey)}</p>
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
