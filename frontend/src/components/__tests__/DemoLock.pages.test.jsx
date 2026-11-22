import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, within, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

// Review item 2: on the read-only demo no write control stays enabled. Each
// page is rendered as the demo user; every control that would write is
// disabled and its tooltip says why. The same pages rendered as an ordinary
// user keep their controls (the last block), so the lock is the demo's only.

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
vi.mock('i18next', () => ({ default: { isInitialized: true, t: (key) => key } }));
vi.mock('../../utils/permissions', () => ({ can: () => true, canOnProject: () => true, getRoleDisplayName: (r) => r }));
vi.mock('../../utils/edition', () => ({ enterpriseProjectTabs: [] }));
vi.mock('../../services/project.service', () => ({
  ProjectService: { GetProjects: vi.fn(), GetProjectDetails: vi.fn(() => Promise.resolve({ id: 1, name: 'Shopfront' })) },
}));
vi.mock('../../services/deployment.service', () => ({ default: { list: vi.fn(() => Promise.resolve([])) } }));
vi.mock('../../services/notification.service', () => ({
  default: {
    getAllNotifications: vi.fn(() => Promise.resolve({ data: [
      { id: 1, subject: 'Checkout is failing', message: 'pricing returns HTTP 500', is_read: false, created_at: new Date().toISOString() },
      { id: 2, subject: 'Cache cold', message: 'redis restarted', is_read: true, created_at: new Date().toISOString() },
    ] })),
    getReadNotifications: vi.fn(() => Promise.resolve({ data: [] })),
    getUnreadCount: vi.fn(() => Promise.resolve({ data: { unread_count: 1 } })),
  },
}));
vi.mock('../../services/auth.service', () => ({ default: { getUser: () => ({ _id: 5 }) } }));
vi.mock('../../services/profile.service', () => ({
  default: { getOne: vi.fn(() => Promise.resolve({ data: { first_name: 'Demo', last_name: 'Visitor', email: 'demo@example.com', avatar: '/media/a.png', role: 'VIEWER' } })) },
}));
vi.mock('../../hooks/useServiceProjects', () => ({
  PAGE_SIZE: 10,
  useServiceProjects: () => ({
    projectName: 'Shopfront', services: [{ id: 3, name: 'pricing', service_type: 'CUSTOM' }], loading: false,
    currentPage: 1, totalPages: 1, totalServices: 1, handleServiceCreated: vi.fn(), goToPage: vi.fn(),
    showModal: false, handleOpenModal: vi.fn(), handleCloseModal: vi.fn(), selectedService: null,
    showDetailsModal: false, loadingDetails: false, detailsError: null, handleViewDetails: vi.fn(),
    handleCloseDetailsModal: vi.fn(), handleDelete: vi.fn(), refreshServices: vi.fn(),
  }),
}));
vi.mock('../ServiceProjects/ServiceDetailsModal', () => ({ default: () => null }));
vi.mock('../ServiceProjects/AddServiceWizard', () => ({ default: () => null }));
vi.mock('../ServiceProjects/DeploymentsPanel', () => ({ default: () => null }));
vi.mock('../ServiceProjects/DataCheckPanel', () => ({ default: () => null }));

import { ProjectService } from '../../services/project.service';
import IssuePanel from '../issues/IssuePanel';
import Project from '../Project';
import ServiceProjects from '../serviceProjects';
import NotificationPanel from '../NotificationPanel';
import Profile from '../../pages/Profile';

const REASON = 'demo.readOnlyNotice';
const signIn = (user) => window.localStorage.getItem.mockImplementation((k) => (k === 'user' ? JSON.stringify(user) : null));
const noop = () => {};
const issue = { id: 7, severity: 'CRITICAL', status: 'OPEN', description: 'pricing fails', component: 'pricing', root_cause: 'rounding', recommendation: 'roll back' };

const expectLocked = (el) => {
  expect(el).toBeDisabled();
  expect(el).toHaveAttribute('title', REASON);
};
const button = (name) => screen.getByRole('button', { name });

const pages = {
  drawerOpen: () => render(<MemoryRouter><IssuePanel issue={issue} onClose={noop} onResolve={noop} onMute={noop} onReopen={noop} onAcknowledge={noop} onAskAI={noop} onCopyLink={noop} /></MemoryRouter>),
  drawerResolved: () => render(<MemoryRouter><IssuePanel issue={{ ...issue, status: 'RESOLVED' }} onClose={noop} onResolve={noop} onMute={noop} onReopen={noop} onAcknowledge={noop} onAskAI={noop} onCopyLink={noop} /></MemoryRouter>),
  projects: () => render(<MemoryRouter><Project /></MemoryRouter>),
  services: () => render(<MemoryRouter initialEntries={['/dash/projects/1']}><Routes><Route path="/dash/projects/:projectId" element={<ServiceProjects />} /></Routes></MemoryRouter>),
  notifications: () => render(<MemoryRouter><NotificationPanel unreadCount={1} /></MemoryRouter>),
  profile: () => render(<MemoryRouter><Profile /></MemoryRouter>),
};

describe('read-only demo: no enabled write control', () => {
  beforeEach(() => {
    signIn({ username: 'demo', is_demo: true });
    ProjectService.GetProjects.mockResolvedValue([{ id: 1, name: 'Shopfront', description: '', environments: [] }]);
  });
  afterEach(() => window.localStorage.getItem.mockReset());

  it('issue drawer: Resolve, Mute, Acknowledge and Reopen are off; reading actions stay on', () => {
    const { unmount } = pages.drawerOpen();
    ['issues.panel.resolve', 'issues.panel.mute', 'issues.panel.acknowledge'].forEach((n) => expectLocked(button(new RegExp(`${n}$`))));
    expect(button(/issues.panel.copyLink/)).toBeEnabled();
    expect(button(/issues.panel.askAI/)).toBeEnabled();
    unmount();
    pages.drawerResolved();
    expectLocked(button(/issues.panel.reopen/));
  });

  it('Projects: New Project, edit and delete are off', async () => {
    pages.projects();
    await screen.findByText('Shopfront');
    expectLocked(button(/projects.newProject/));
    expectLocked(button('common.edit'));
    expectLocked(button('common.delete'));
  });

  it('project services: Add new Service and delete are off', async () => {
    pages.services();
    await screen.findByText('pricing');
    expectLocked(button(/services.addNew/));
    expectLocked(button('common.delete'));
  });

  it('notifications: Mark all as read, Clear all and the per-item actions are off; filters stay on', async () => {
    pages.notifications();
    await screen.findByText('Checkout is failing');
    expectLocked(button(/notifications.panel.markAllRead/));
    expectLocked(button(/notifications.panel.clearAll/));
    const perItem = screen.getAllByRole('button', { name: /notifications.panel.tooltips\.(markRead|markUnread|delete)/ });
    expect(perItem).toHaveLength(4);
    perItem.forEach(expectLocked);
    within(screen.getByRole('tablist')).getAllByRole('tab').forEach((tab) => expect(tab).toBeEnabled());
  });

  it('Profile: Edit, Update Password, the photo upload and its removal are off', async () => {
    const { container } = pages.profile();
    await screen.findByText('demo@example.com');
    expectLocked(button(/common.edit/));
    expectLocked(button('profile.updatePassword'));
    await waitFor(() => expectLocked(button('profile.removePhoto')));
    expect(container.querySelector('input[type="file"]')).toBeDisabled();
  });
});

describe('any other user keeps the same controls', () => {
  beforeEach(() => {
    signIn({ username: 'ada', is_demo: false, avatar: '' });
    ProjectService.GetProjects.mockResolvedValue([{ id: 1, name: 'Shopfront', description: '', environments: [] }]);
  });
  afterEach(() => window.localStorage.getItem.mockReset());

  it('drawer, Projects, services, notifications and Profile are untouched', async () => {
    let view = pages.drawerOpen();
    expect(button(/issues.panel.resolve$/)).toBeEnabled();
    expect(button(/issues.panel.resolve$/)).not.toHaveAttribute('title');
    view.unmount();
    view = pages.projects();
    await screen.findByText('Shopfront');
    expect(button(/projects.newProject/)).toBeEnabled();
    expect(button('common.delete')).toBeEnabled();
    expect(button('common.delete')).toHaveAttribute('title', 'common.delete');
    view.unmount();
    view = pages.services();
    await screen.findByText('pricing');
    expect(button(/services.addNew/)).toBeEnabled();
    view.unmount();
    view = pages.notifications();
    await screen.findByText('Checkout is failing');
    expect(button(/notifications.panel.clearAll/)).toBeEnabled();
    view.unmount();
    pages.profile();
    await screen.findByText('demo@example.com');
    expect(button(/common.edit/)).toBeEnabled();
    expect(button('profile.updatePassword')).toBeEnabled();
  });
});
