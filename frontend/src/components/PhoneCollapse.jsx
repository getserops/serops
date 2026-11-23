import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/**
 * On a phone, a panel reduced to its header (title and its one-line
 * summary), which a tap opens. Anywhere else it renders the panel as is.
 * The panel is a .chart-card with a .chart-header; the stylesheet hides the
 * rest while collapsed (Dashboard.css).
 */
const PhoneCollapse = ({ phone, title, children }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!phone) return children;
  return (
    <div className={`phone-collapse ${open ? 'is-open' : 'is-collapsed'}`}>
      <button
        type="button"
        className="phone-collapse-toggle"
        aria-expanded={open}
        aria-label={t(open ? 'dashboard.panel.hide' : 'dashboard.panel.show', { title })}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown size={18} aria-hidden="true" />
      </button>
      {children}
    </div>
  );
};

export default PhoneCollapse;
