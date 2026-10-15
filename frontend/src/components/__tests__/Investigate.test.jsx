import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { clampWindow, deployWindow, validateWindow, MINUTE } from '../investigate/window';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => (opts && typeof opts.count === 'number' ? `${key}:${opts.count}` : key) }),
}));

const svc = vi.hoisted(() => ({ options: vi.fn(), list: vi.fn(), get: vi.fn(), create: vi.fn() }));
vi.mock('../../services/investigation.service', () => ({ default: svc }));

import Investigate, { defaultEnvironment } from '../investigate/Investigate';

const NOW = new Date('2026-10-14T12:00:00Z');
const OPTIONS = {
  limits: { min_window_minutes: 5, max_window_hours: 6, hint_max_length: 500, max_lookback_days: 30 },
  projects: [{
    id: 7, name: 'api',
    environments: [{ id: 3, name: 'production', display_name: 'Production' }, { id: 4, name: 'staging', display_name: 'Staging' }],
    deployments: [{ id: 9, name: 'prod-eu', environment_id: 3 }],
    services: ['checkout', 'payments'],
    last_deploy_at: '2026-10-14T11:40:00Z',
  }],
};

describe('window rules', () => {
  it('clamps to now and to the maximum length', () => {
    const w = clampWindow(new Date(NOW - 10 * 60 * MINUTE), new Date(NOW.getTime() + 60 * MINUTE), {}, NOW);
    expect(w.end).toEqual(NOW);
    expect(w.end - w.start).toBe(6 * 60 * MINUTE);
  });

  it('stretches a window that is too short', () => {
    const w = clampWindow(new Date(NOW - 2 * MINUTE), NOW, {}, NOW);
    expect(w.end - w.start).toBe(5 * MINUTE);
  });

  it('analyses a deploy from 5 minutes before to 30 after, never past now', () => {
    const w = deployWindow('2026-10-14T11:50:00Z', {}, NOW);
    expect(w.start.toISOString()).toBe('2026-10-14T11:45:00.000Z');
    expect(w.end).toEqual(NOW);
  });

  it('names what is wrong with a window', () => {
    expect(validateWindow(new Date(NOW - 30 * MINUTE), NOW, {}, NOW)).toBeNull();
    expect(validateWindow(new Date(NOW - 2 * MINUTE), NOW, {}, NOW)).toBe('tooShort');
    expect(validateWindow(new Date(NOW - 7 * 60 * MINUTE), NOW, {}, NOW)).toBe('tooLong');
    expect(validateWindow(NOW, new Date(NOW.getTime() + 10 * MINUTE), {}, NOW)).toBe('future');
    expect(validateWindow(null, NOW, {}, NOW)).toBe('invalid');
  });
});

describe('default environment', () => {
  it('prefers production over the first environment', () => {
    const project = { environments: [{ id: 1, name: 'development' }, { id: 2, name: 'Production' }] };
    expect(defaultEnvironment(project).id).toBe(2);
    expect(defaultEnvironment({ environments: [{ id: 5, name: 'staging' }] }).id).toBe(5);
    expect(defaultEnvironment({ environments: [] })).toBeNull();
  });
});

describe('Investigate page', () => {
  beforeEach(() => {
    Object.values(svc).forEach((f) => f.mockReset());
    svc.options.mockResolvedValue(OPTIONS);
    svc.list.mockResolvedValue({ results: [], count: 0 });
    window.localStorage.getItem.mockImplementation((k) => (k === 'user' ? JSON.stringify({ role: 'user' }) : null));
  });

  const renderAt = (path = '/dash/investigate') => render(
    <MemoryRouter initialEntries={[path]}><Investigate /></MemoryRouter>,
  );

  it('prefills scope and window from the link that opened it', async () => {
    renderAt('/dash/investigate?project_id=7&deployment_id=9&services=payments&start=2026-10-14T10:00:00Z&end=2026-10-14T11:00:00Z');
    await waitFor(() => expect(screen.getByDisplayValue('prod-eu')).toBeInTheDocument());
    expect(screen.getByDisplayValue('Production')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'payments' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'checkout' })).toHaveAttribute('aria-pressed', 'false');
  });

  it('starts an investigation with an ISO window and shows its progress', async () => {
    svc.create.mockResolvedValue({
      id: 1, status: 'queued', project: { id: 7, name: 'api' }, environment: { id: 3, name: 'production' },
      services: [], window_start: '2026-10-14T11:30:00Z', window_end: '2026-10-14T12:00:00Z', counts: {},
    });
    renderAt();
    await waitFor(() => expect(screen.getByDisplayValue('api')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('investigate.hint.placeholder'), { target: { value: ' Checkout slow ' } });
    fireEvent.click(screen.getByRole('button', { name: /investigate.run/ }));
    await waitFor(() => expect(svc.create).toHaveBeenCalled());
    const body = svc.create.mock.calls[0][0];
    expect(body).toMatchObject({ project_id: 7, environment_id: 3, hint: 'Checkout slow', notify_routing: false });
    expect(new Date(body.window_end) - new Date(body.window_start)).toBeCloseTo(30 * MINUTE, -4);
    expect(await screen.findAllByText('investigate.status.queued')).not.toHaveLength(0);
  });

  it('shows the API reason when it refuses', async () => {
    svc.create.mockRejectedValue({ response: { status: 429, data: { error: 'too_many_running', message: '2 investigations are already running.' } } });
    renderAt();
    await waitFor(() => expect(screen.getByDisplayValue('api')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /investigate.run/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('2 investigations are already running.');
  });

  it('checks the window before calling the API', async () => {
    renderAt('/dash/investigate?start=2026-10-14T10:00:00Z&end=2026-10-14T11:00:00Z');
    await waitFor(() => expect(screen.getByDisplayValue('api')).toBeInTheDocument());
    const [from] = screen.getAllByDisplayValue(/T/);
    fireEvent.change(from, { target: { value: '2020-01-01T10:00' } });
    fireEvent.click(screen.getByRole('button', { name: /investigate.run/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/investigate.window/);
    expect(svc.create).not.toHaveBeenCalled();
  });

  it('cannot be started from the demo', async () => {
    window.localStorage.getItem.mockImplementation((k) => (k === 'user' ? JSON.stringify({ role: 'viewer', is_demo: true }) : null));
    renderAt();
    expect(await screen.findByText('investigate.demoNotice')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('button', { name: /investigate.run/ })).toBeDisabled());
  });

  it('lists past runs with a link to their analysis', async () => {
    svc.list.mockResolvedValue({ count: 1, results: [{
      id: 5, status: 'done', issue_count: 2, batch_id: 'api-batch-1', project: { id: 7, name: 'api' },
      environment: { id: 3, name: 'production' }, hint: 'slow', requested_by: { id: 1, name: 'Alice' },
      created_at: '2026-10-14T11:00:00Z', window_start: '2026-10-14T10:00:00Z', window_end: '2026-10-14T11:00:00Z',
    }] });
    renderAt();
    const link = await screen.findByRole('link', { name: 'investigate.result.open' });
    expect(link).toHaveAttribute('href', '/dash/data/details/api-batch-1');
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });
});
