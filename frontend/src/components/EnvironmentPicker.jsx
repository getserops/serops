import React from 'react';
import { Dropdown } from 'react-bootstrap';
import { ChevronDown, Check } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useDeployment } from '../context/DeploymentContext';

// The common environment names. A custom value set elsewhere (the
// cluster picker's env field, a shared link) is listed too.
export const ENVIRONMENTS = ['production', 'staging', 'dev'];

// Top-bar environment filter. Writes the global deployment filter, which
// every API call already forwards, so all pages follow the same choice.
const EnvironmentPicker = () => {
  const { t } = useTranslation();
  const { filter, setField } = useDeployment();
  const current = filter.environment || '';
  const options = current && !ENVIRONMENTS.includes(current)
    ? [...ENVIRONMENTS, current]
    : ENVIRONMENTS;

  return (
    <Dropdown className="app-picker">
      <Dropdown.Toggle as="button" type="button" className="app-picker-toggle" aria-label={t('nav.environmentFilter')}>
        <span className="app-picker-key">{t('nav.environment')}</span>
        <span>{current || t('nav.allEnvironments')}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </Dropdown.Toggle>
      <Dropdown.Menu>
        <Dropdown.Item as="button" active={!current} onClick={() => setField('environment', '')}>
          <span className="app-picker-check">{!current && <Check size={14} aria-hidden="true" />}</span>
          {t('nav.allEnvironments')}
        </Dropdown.Item>
        {options.map((env) => (
          <Dropdown.Item as="button" key={env} active={current === env} onClick={() => setField('environment', env)}>
            <span className="app-picker-check">{current === env && <Check size={14} aria-hidden="true" />}</span>
            {env}
          </Dropdown.Item>
        ))}
      </Dropdown.Menu>
    </Dropdown>
  );
};

export default EnvironmentPicker;
