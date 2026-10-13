import React, { useState } from 'react';
import { FaChevronRight, FaChevronDown } from 'react-icons/fa';
import './SettingsLayout.css';

const CollapsibleSection = ({
    title,
    description,
    children,
    defaultExpanded = false,
    className = ''
}) => {
    const [isExpanded, setIsExpanded] = useState(defaultExpanded);

    return (
        <div className={`gl-settings-section ${className}`}>
            <div
                className="gl-settings-header"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="gl-toggle-icon">
                    {isExpanded ? <FaChevronDown /> : <FaChevronRight />}
                </div>
                <div className="gl-settings-header-content">
                    <h3 className="gl-settings-title">{title}</h3>
                    {description && <p className="gl-settings-description">{description}</p>}
                </div>
            </div>

            <div className={`gl-settings-content ${isExpanded ? 'expanded' : ''}`}>
                <div className="gl-settings-content-inner">
                    {children}
                </div>
            </div>
        </div>
    );
};

export default CollapsibleSection;
