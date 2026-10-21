/**
 * The header above each Integrations tab's list: title, count, one line of
 * context, and the tab's add action on the right. Every tab (source
 * control, CI/CD, logs, metrics) uses it, so the action is always in the
 * same place.
 */
import React from 'react';
import { Badge } from 'react-bootstrap';

const IntegrationsSectionHeader = ({ title, count, description, action }) => (
    <div className="integrations-section-head">
        <div className="integrations-section-text">
            <h2 className="integrations-section-title">
                {title}
                <Badge bg="secondary">{count}</Badge>
            </h2>
            {description && <p className="integrations-section-desc">{description}</p>}
        </div>
        {action}
    </div>
);

export default IntegrationsSectionHeader;
