import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const MEMBERS = [
  { id: 1, email: 'demo@serops.ai', first_name: 'SerOps', last_name: 'Demo', role: 'admin', is_active: true, last_login: '2026-11-19T10:00:00Z' },
  { id: 2, email: 'fleet.on-call@acme.example', first_name: 'Fleet', last_name: 'on-call', role: 'user', is_active: true, last_login: '2026-11-19T10:00:00Z' },
];
vi.mock('../../services/organisation.service', () => ({
  OrganisationService: {
    getTeamMembers: vi.fn().mockImplementation(() => Promise.resolve({ users: MEMBERS })),
    getRoles: vi.fn().mockResolvedValue({ custom: [] }),
    inviteTeamMember: vi.fn(), updateTeamMember: vi.fn(), removeTeamMember: vi.fn(),
  },
}));
vi.mock('../../services/enterpriseSettings.service', () => ({
  default: { getSSOConfig: vi.fn().mockResolvedValue({}) },
}));
vi.mock('../../utils/permissions', () => ({ can: () => true, getRoleDisplayName: (r) => r, getRoleColor: () => 'secondary' }));
vi.mock('../../utils/edition', () => ({ hasFeature: () => false, useEdition: () => ({}) }));
const who = vi.hoisted(() => ({ demo: false }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => who.demo }));

import TeamManagement from '../TeamManagement';

const show = () => render(<MemoryRouter><TeamManagement /></MemoryRouter>);

describe('TeamManagement: the demo shows the team without the buttons the server refuses', () => {
  beforeEach(() => {
    const store = { user: JSON.stringify({ id: 1, role: 'admin' }) };
    vi.stubGlobal('localStorage', {
      getItem: (k) => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: (k) => { delete store[k]; },
    });
  });

  it('a normal organisation sees invite, edit and remove', async () => {
    who.demo = false;
    show();
    expect(await screen.findByText('fleet.on-call@acme.example')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /team\.inviteUser/ })).toBeInTheDocument();
    expect(screen.getByTitle('team.editUser')).toBeInTheDocument();
    expect(screen.getByTitle('team.removeUser')).toBeInTheDocument();
  });

  it('the demo sees the members and none of the three buttons', async () => {
    who.demo = true;
    show();
    expect(await screen.findByText('fleet.on-call@acme.example')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /team\.inviteUser/ })).toBeNull();
    expect(screen.queryByTitle('team.editUser')).toBeNull();
    expect(screen.queryByTitle('team.removeUser')).toBeNull();
  });

  it('the demo shows no Actions column and no text about inviting or removing', async () => {
    who.demo = true;
    show();
    await screen.findByText('fleet.on-call@acme.example');
    expect(screen.queryByText('team.actions')).toBeNull();
    expect(screen.queryByText('team.membersDesc')).toBeNull();
  });

  it('a normal organisation keeps the Actions column and the description', async () => {
    who.demo = false;
    show();
    await screen.findByText('fleet.on-call@acme.example');
    expect(screen.getByText('team.actions')).toBeTruthy();
    expect(screen.getByText('team.membersDesc')).toBeTruthy();
  });
});
