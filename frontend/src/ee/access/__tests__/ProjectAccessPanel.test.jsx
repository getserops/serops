import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { edition, getAccess, updateAccess } = vi.hoisted(() => ({
  edition: { features: ['project_access'] }, getAccess: vi.fn(), updateAccess: vi.fn(),
}));
vi.mock('../../../utils/edition', () => ({
  useEdition: () => edition,
  hasFeature: (e, code) => e.features.includes(code),
}));
vi.mock('../service', () => ({
  AccessService: { getProjectAccess: (...a) => getAccess(...a), updateProjectAccess: (...a) => updateAccess(...a) },
}));
vi.mock('../../../services/organisation.service', () => ({
  OrganisationService: { getTeams: async () => [{ id: 1, name: 'Payments' }, { id: 2, name: 'SRE' }] },
}));

import ProjectAccessPanel from '../ProjectAccessPanel';

beforeEach(() => {
  getAccess.mockResolvedValue({ project_id: 9, access_mode: 'organisation', grants: [{ team_id: 1, team_name: 'Payments', role: 'viewer' }] });
  updateAccess.mockImplementation(async (_id, body) => ({ project_id: 9, ...body, grants: body.grants }));
  edition.features = ['project_access'];
});

describe('ProjectAccessPanel', () => {
  it('restricts the project and grants a second team', async () => {
    render(<ProjectAccessPanel projectId={9} />);
    expect(await screen.findByText('Payments')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: /projectAccess.restricted/ }));
    fireEvent.change(screen.getByLabelText('projectAccess.addTeam'), { target: { value: '2' } });
    const roles = screen.getAllByLabelText('projectAccess.role');
    fireEvent.change(roles[1], { target: { value: 'user' } });
    fireEvent.click(screen.getByText('common.saveChanges'));
    await waitFor(() => expect(updateAccess).toHaveBeenCalledWith(9, {
      access_mode: 'restricted',
      grants: [{ team_id: 1, role: 'viewer' }, { team_id: 2, role: 'user' }],
    }));
  });

  it('removes a team', async () => {
    render(<ProjectAccessPanel projectId={9} />);
    fireEvent.click(await screen.findByLabelText('projectAccess.remove'));
    fireEvent.click(screen.getByText('common.saveChanges'));
    await waitFor(() => expect(updateAccess).toHaveBeenCalledWith(9, { access_mode: 'organisation', grants: [] }));
  });

  it('without a license: cannot restrict, add teams or raise a role; can remove', async () => {
    edition.features = [];
    getAccess.mockResolvedValue({ project_id: 9, access_mode: 'organisation', grants: [{ team_id: 1, team_name: 'Payments', role: 'user' }] });
    render(<ProjectAccessPanel projectId={9} />);
    expect(await screen.findByText('Payments')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('ee.access.accessUnlicensed');
    expect(screen.getByRole('radio', { name: /projectAccess.restricted/ })).toBeDisabled();
    expect(screen.queryByLabelText('projectAccess.addTeam')).not.toBeInTheDocument();
    const options = [...screen.getByLabelText('projectAccess.role').querySelectorAll('option')].map((o) => o.value);
    expect(options).toEqual(['viewer', 'user']);
    fireEvent.click(screen.getByLabelText('projectAccess.remove'));
    fireEvent.click(screen.getByText('common.saveChanges'));
    await waitFor(() => expect(updateAccess).toHaveBeenCalledWith(9, { access_mode: 'organisation', grants: [] }));
  });
});
