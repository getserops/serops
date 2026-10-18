import React from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

/**
 * The one page header: breadcrumb, title (plus optional badges), one
 * line of context, and the page's actions on the right. The breadcrumb
 * is the only back link — pages don't add their own Back button.
 *
 * crumbs: [{ label, to? }] — the last one is the current page.
 */
const PageHeader = ({ crumbs, title, badges, subtitle, actions, titleAs = 'h1', className = '' }) => {
  const { t } = useTranslation();
  const Title = titleAs;
  return (
    <header className={`page-header ${className}`}>
      <div className="page-header-text">
        {crumbs && crumbs.length > 0 && (
          <nav aria-label={t('common.breadcrumb')}>
            <ol className="page-header-crumbs">
              {crumbs.map((c, i) => {
                const last = i === crumbs.length - 1;
                return (
                  <li key={`${c.label}-${i}`} aria-current={last ? 'page' : undefined} className={c.mono ? 'ds-mono' : undefined}>
                    {c.to && !last ? <Link to={c.to}>{c.label}</Link> : c.label}
                  </li>
                );
              })}
            </ol>
          </nav>
        )}
        <div className="page-header-title-row">
          <Title className="page-header-title">{title}</Title>
          {badges}
        </div>
        {subtitle && <div className="page-header-subtitle">{subtitle}</div>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  );
};

export default PageHeader;
