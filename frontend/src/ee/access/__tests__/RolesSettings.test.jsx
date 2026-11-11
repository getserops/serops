import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => (opts && opts.defaultValue !== undefined && key.startsWith('roles.perm.') ? opts.defaultValue : key) }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('react-router-dom', () => ({ Link: ({ children }) => children }));
vi.mock('../../../utils/permissions', () => ({ usePermissions: () => (code) => code === 'team.manage' }));

const { edition, getRoles, createRole, deleteRole } = vi.hoisted(() => ({
  edition: { features: ['custom_roles'] },
  getRoles: vi.fn(),
  createRole: vi.fn(),
  deleteRole: vi.fn(),
}));
vi.mock('../../../utils/edition', () => ({
  useEdition: () => edition,
  hasFeature: (e, code) => e.features.includes(code),
}));
vi.mock('../../../services/organisation.service', () => ({
  OrganisationService: { getRoles: (...a) => getRoles(...a) },
}));
vi.mock('../service', () => ({
  AccessService: { createRole: (...a) => createRole(...a), updateRole: vi.fn(), deleteRole: (...a) => deleteRole(...a) },
}));

import RolesSettings from '../RolesSettings';

const CATALOGUE = ['self.manage', 'org.read', 'batch.read', 'batch.analyze', 'team.manage']
  .map((code) => ({ code, description: `desc ${code}` }));

beforeEach(() => {
  getRoles.mockResolvedValue({
    builtin: [{ key: 'viewer', name: 'Viewer', permissions: ['self.manage', 'org.read', 'batch.read'] }],
    custom: [{ id: 3, key: 'custom:3', name: 'Analyst', description: 'Runs analyses', permissions: ['batch.analyze'], member_count: 2 }],
    catalogue: CATALOGUE,
    always_granted: ['org.read', 'self.manage'],
    implies: { 'batch.analyze': 'batch.read' },
  });
  createRole.mockResolvedValue({});
  deleteRole.mockResolvedValue();
  edition.features = ['custom_roles'];
});

describe('RolesSettings', () => {
  it('lists custom and built-in roles', async () => {
    render(<RolesSettings />);
    expect(await screen.findByText('Analyst')).toBeInTheDocument();
    expect(screen.getByText('Runs analyses')).toBeInTheDocument();
    expect(screen.getByText('Viewer')).toBeInTheDocument();
  });

  it('locks what every role holds and what a pick needs', async () => {
    render(<RolesSettings />);
    fireEvent.click(await screen.findByText('roles.create'));
    const always = screen.getByLabelText(/desc self\.manage/);
    expect(always).toBeChecked();
    expect(always).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/desc batch\.analyze/));
    const read = screen.getByLabelText(/desc batch\.read/);
    expect(read).toBeChecked();
    expect(read).toBeDisabled();
  });

  it('creates a role with the picked permissions', async () => {
    render(<RolesSettings />);
    fireEvent.click(await screen.findByText('roles.create'));
    fireEvent.change(screen.getByLabelText('roles.name'), { target: { value: 'Responder' } });
    fireEvent.click(screen.getByLabelText(/desc batch\.analyze/));
    fireEvent.click(screen.getByText('common.save'));
    await waitFor(() => expect(createRole).toHaveBeenCalledWith({ name: 'Responder', description: '', permissions: ['batch.analyze'] }));
  });

  it('without a license: a note, no create or edit, delete still offered', async () => {
    edition.features = [];
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<RolesSettings />);
    expect(await screen.findByText('Analyst')).toBeInTheDocument();
    expect(screen.getByRole('note')).toHaveTextContent('ee.access.rolesUnlicensed');
    expect(screen.queryByText('roles.create')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('roles.edit')).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('roles.delete'));
    await waitFor(() => expect(deleteRole).toHaveBeenCalledWith(3));
  });
});
