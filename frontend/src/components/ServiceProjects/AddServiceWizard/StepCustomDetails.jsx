/**
 * StepCustomDetails - Step 2c: Custom service details
 * For Custom service type - simple name and description entry
 */

import React from "react";
import { Form } from "react-bootstrap";
import { useTranslation } from "react-i18next";

const StepCustomDetails = ({ formData, updateFormData }) => {
    const { t } = useTranslation();
    return (
        <div className="wizard-step-content">
            <h5 className="wizard-step-title">{t('addServiceWizard.custom.title')}</h5>
            <p className="wizard-step-subtitle">
                {t('addServiceWizard.custom.subtitle')}
            </p>

            {/* Service Name */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-customdetails-1">{t('addServiceWizard.serviceNameRequired')}</label>
                <Form.Control id="wizard-customdetails-1"
                    type="text"
                    placeholder={t('addServiceWizard.custom.namePlaceholder')}
                    value={formData.serviceName || ""}
                    onChange={(e) => updateFormData({ serviceName: e.target.value })}
                    className="rounded-3"
                    required
                />
            </div>

            {/* Description */}
            <div className="wizard-form-section">
                <label className="wizard-form-label" htmlFor="wizard-customdetails-2">{t('addService.description')}</label>
                <Form.Control id="wizard-customdetails-2"
                    as="textarea"
                    rows={3}
                    placeholder={t('serviceForms.descriptionPlaceholder')}
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
