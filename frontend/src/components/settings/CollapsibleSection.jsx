import React from 'react';
import './SettingsLayout.css';

// A settings section: a card with a title, one line of context and the
// form below. Sections stay open — settings pages are short enough once
// choices are compact, and a hidden form is a form nobody finds.
// (Name kept so the pages that use it don't change; `defaultExpanded`
// is accepted and ignored.)
// eslint-disable-next-line no-unused-vars
const CollapsibleSection = ({ title, description, children, defaultExpanded, actions, className = '' }) => (
    <section className={`ds-settings-section ${className}`}>
        <header className="ds-settings-section-head">
            <div className="ds-settings-section-text">
                <h2 className="ds-settings-section-title">{title}</h2>
                {description && <p className="ds-settings-section-desc">{description}</p>}
            </div>
            {actions && <div className="ds-settings-section-actions">{actions}</div>}
        </header>
        <div className="ds-settings-section-body">{children}</div>
    </section>
);

export default CollapsibleSection;
