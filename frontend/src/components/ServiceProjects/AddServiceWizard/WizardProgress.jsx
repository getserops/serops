/**
 * WizardProgress - Step indicator for the Add Service wizard
 * Shows current progress through the wizard steps
 */

import React from "react";
import "./wizard.css";

const WizardProgress = ({ currentStep, totalSteps, stepLabels }) => {
    return (
        <div className="wizard-progress">
            <div className="wizard-progress-bar">
                {Array.from({ length: totalSteps }, (_, i) => {
                    const stepNum = i + 1;
                    const isActive = stepNum === currentStep;
                    const isCompleted = stepNum < currentStep;

                    return (
                        <React.Fragment key={stepNum}>
                            {/* Step circle */}
                            <div
                                className={`wizard-step ${isActive ? 'active' : ''} ${isCompleted ? 'completed' : ''}`}
                            >
                                {isCompleted ? (
                                    <span className="step-check">✓</span>
                                ) : (
                                    <span className="step-number">{stepNum}</span>
                                )}
                            </div>

                            {/* Connector line (except after last step) */}
                            {stepNum < totalSteps && (
                                <div className={`wizard-connector ${isCompleted ? 'completed' : ''}`} />
                            )}
                        </React.Fragment>
                    );
                })}
            </div>

            {/* Step labels */}
            <div className="wizard-labels">
                {stepLabels.map((label, i) => (
                    <span
                        key={i}
                        className={`wizard-label ${i + 1 === currentStep ? 'active' : ''}`}
                    >
                        {label}
                    </span>
                ))}
            </div>
        </div>
    );
};

export default WizardProgress;
