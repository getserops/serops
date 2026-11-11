import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { useState } from 'react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));

import SSORoleMapping from '../settings/SSORoleMapping';

const ROLES = [{ value: 'viewer', label: 'Viewer' }, { value: 'user', label: 'User' }, { value: 'admin', label: 'Admin' }];

function Harness({ initial, onState }) {
  const [sso, setSso] = useState(initial);
  onState(sso);
  return <SSORoleMapping sso={sso} roles={ROLES} onChange={setSso} />;
}

const setup = (initial = {}) => {
  let state;
  render(<Harness initial={{ role_mappings: [], email_domains_editable: true, ...initial }} onState={(s) => { state = s; }} />);
  return () => state;
};

describe('SSORoleMapping', () => {
  it('adds, edits, reorders and removes rules', () => {
    const state = setup();
    expect(screen.getByText('security.noRules')).toBeInTheDocument();
    fireEvent.click(screen.getByText('security.addRule'));
    fireEvent.click(screen.getByText('security.addRule'));
    const groups = screen.getAllByLabelText('security.ruleGroup');
    fireEvent.change(groups[0], { target: { value: 'sre' } });
    fireEvent.change(groups[1], { target: { value: 'platform-admins' } });
    fireEvent.change(screen.getAllByLabelText('security.ruleRole')[1], { target: { value: 'admin' } });
    fireEvent.click(screen.getAllByLabelText('security.moveUp')[1]);
    expect(state().role_mappings).toEqual([{ group: 'platform-admins', role: 'admin' }, { group: 'sre', role: 'viewer' }]);
    fireEvent.click(screen.getAllByLabelText('security.removeRule')[1]);
    expect(state().role_mappings).toEqual([{ group: 'platform-admins', role: 'admin' }]);
  });

  it('offers refusing the sign-in as the default', () => {
    const state = setup({ default_role: 'viewer' });
    fireEvent.change(screen.getByLabelText('security.defaultRole'), { target: { value: 'deny' } });
    expect(state().default_role).toBe('deny');
  });

  it('locks email domains for organisation admins of a multi-org install', () => {
    setup({ email_domains: ['acme.test'], email_domains_editable: false });
    const input = screen.getByLabelText('security.emailDomains');
    expect(input).toBeDisabled();
    expect(input.value).toBe('acme.test');
    expect(screen.getByText('security.emailDomainsStaffOnly')).toBeInTheDocument();
  });
});
