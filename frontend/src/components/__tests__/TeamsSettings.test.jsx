import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('../../utils/permissions', () => ({
  usePermissions: () => (code) => code === 'team.manage',
  getRoleDisplayName: (r) => r,
}));
const createTeam = vi.fn(async () => ({}));
vi.mock('../../services/organisation.service', () => ({
  OrganisationService: {
    getTeams: async () => [{ id: 1, name: 'SRE', description: '', members: [{ id: 5, email: 'bo@x.test', name: 'Bo', source: 'sso' }],
                             projects: [{ id: 3, name: 'payments', role: 'admin' }] }],
    getTeamMembers: async () => ({ users: [{ id: 5, email: 'bo@x.test', first_name: 'Bo', role: 'user' },
                                           { id: 6, email: 'al@x.test', first_name: 'Al', role: 'viewer' }] }),
    createTeam: (...a) => createTeam(...a),
    updateTeam: vi.fn(), deleteTeam: vi.fn(),
  },
}));

import TeamsSettings from '../settings/TeamsSettings';

describe('TeamsSettings', () => {
  it('lists teams with SSO members and projects', async () => {
    render(<TeamsSettings />);
    expect(await screen.findByText('SRE')).toBeInTheDocument();
    expect(screen.getByText('SSO')).toBeInTheDocument();
    expect(screen.getByText('payments · admin')).toBeInTheDocument();
  });

  it('creates a team with members', async () => {
    render(<TeamsSettings />);
    fireEvent.click(await screen.findByText('teams.create'));
    fireEvent.change(screen.getByLabelText('teams.name'), { target: { value: 'Payments' } });
    fireEvent.click(await screen.findByLabelText(/al@x.test/));
    fireEvent.click(screen.getByText('common.save'));
    await waitFor(() => expect(createTeam).toHaveBeenCalledWith({ name: 'Payments', description: '', member_ids: [6] }));
  });
});
