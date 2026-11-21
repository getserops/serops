import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const i18n = vi.hoisted(() => ({ t: (key) => key }));
vi.mock('react-i18next', () => ({ useTranslation: () => i18n }));
vi.mock('i18next', () => ({ default: { isInitialized: true, t: (key) => key } }));
vi.mock('../../utils/permissions', () => ({ can: () => true, canOnProject: () => true }));
vi.mock('../../services/project.service', () => ({
  ProjectService: {
    GetProjects: vi.fn(), GetProjectDetails: vi.fn(), CreateProject: vi.fn(), UpdateProject: vi.fn(), DeleteProject: vi.fn(),
  },
}));

import { ProjectService } from '../../services/project.service';
import Project from '../Project';

const refused = (status, data) => Object.assign(new Error('refused'), { response: { status, data } });
const DEMO = refused(403, { error: 'demo_read_only', message: "You're in the SerOps live demo — sign up to make changes." });

const createOne = async () => {
  render(<MemoryRouter><Project /></MemoryRouter>);
  fireEvent.click(await screen.findByRole('button', { name: /projects\.newProject/ }));
  fireEvent.change(await screen.findByPlaceholderText('projects.namePlaceholder'), { target: { name: 'name', value: 'Checkout' } });
  fireEvent.click(screen.getByRole('button', { name: 'projects.createProject' }));
  await waitFor(() => expect(ProjectService.CreateProject).toHaveBeenCalled());
};

// Seen on the live demo, 21 Nov 2026: the server refused the create (403)
// and the form said "Project created successfully!".
describe('Projects page: a refused create is not shown as a success', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    ProjectService.GetProjects.mockResolvedValue([]);
  });

  it('shows the read-only sentence on the demo, and no success', async () => {
    ProjectService.CreateProject.mockRejectedValue(DEMO);
    await createOne();
    expect(await screen.findByText('demo.readOnlyNotice')).toBeInTheDocument();
    expect(screen.queryByText('projects.createSuccess')).toBeNull();
    expect(screen.queryByText('demo_read_only')).toBeNull();
  });

  it('shows what the server said for any other refusal, and no success', async () => {
    ProjectService.CreateProject.mockRejectedValue(refused(400, { error: 'A project with this name already exists' }));
    await createOne();
    expect(await screen.findByText('A project with this name already exists')).toBeInTheDocument();
    expect(screen.queryByText('projects.createSuccess')).toBeNull();
  });

  it('shows the success only when the server accepted', async () => {
    ProjectService.CreateProject.mockResolvedValue({ id: 4, name: 'Checkout' });
    await createOne();
    expect(await screen.findByText('projects.createSuccess')).toBeInTheDocument();
  });
});
