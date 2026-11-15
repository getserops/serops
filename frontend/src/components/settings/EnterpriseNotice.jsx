/**
 * Shown where an Enterprise feature would be, when it is not licensed on
 * this install (or the Enterprise code is not installed): what it is, and
 * where to read about the license. Never a broken or empty screen.
 */
import React from 'react';
import { useTranslation } from 'react-i18next';

export const PRICING_URL = 'https://serops.ai/pricing';

const EnterpriseNotice = ({ title, children }) => {
    const { t } = useTranslation();
    return (
        <div className="settings-subsection enterprise-notice" role="note">
            <h3 className="settings-subsection-title">
                {title}{' '}
                <span className="badge ds-chip ds-chip-brand">{t('enterprise.label')}</span>
            </h3>
            <p className="form-hint">{children || t('enterprise.notice')}</p>
            <a href={PRICING_URL} target="_blank" rel="noopener noreferrer">{t('enterprise.seePricing')}</a>
        </div>
    );
};

export default EnterpriseNotice;
