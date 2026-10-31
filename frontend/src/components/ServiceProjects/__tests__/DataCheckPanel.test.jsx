import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => (opts && opts.value ? `${key}:${opts.value}` : key) }),
}));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const GetDataRuns = vi.fn();
const CheckData = vi.fn();
const ApplyDataFix = vi.fn();
vi.mock('../../../services/project.service', () => ({
  ProjectService: {
    GetDataRuns: (...a) => GetDataRuns(...a),
    CheckData: (...a) => CheckData(...a),
    ApplyDataFix: (...a) => ApplyDataFix(...a),
  },
}));
let permissions = ['integration.use', 'project.write'];
vi.mock('../../../utils/permissions', () => ({ can: (p) => permissions.includes(p) }));

import DataCheckPanel from '../DataCheckPanel';

const ENVS = [{ id: 5, name: 'production', display_name: 'Production', is_active: true }];

const report = (overrides = {}) => ({
  project: 'api', environment: 'production', environment_values: ['production', 'prod', 'prd'],
  window_minutes: 60, sample_size: 1000, locations: ['logs-*'],
  stages: [
    { key: 'found', count: 40, capped: false },
    { key: 'project', count: 40, capped: false },
    { key: 'environment', count: 40, capped: false },
    { key: 'level', count: 3, capped: false },
    { key: 'services', count: 0, capped: false },
  ],
  seen: { project: [], environment: [], service: [{ value: 'cart', count: 3, registered: false }], level: [] },
  diagnosis: { code: 'unregistered_services', message: 'm', services: ['cart'] },
  fixes: [{ action: 'register_services', names: ['cart'] }],
  ...overrides,
});

describe('DataCheckPanel', () => {
  beforeEach(() => {
    permissions = ['integration.use', 'project.write'];
    GetDataRuns.mockReset().mockResolvedValue({ runs: [] });
    CheckData.mockReset();
    ApplyDataFix.mockReset().mockResolvedValue({ added: ['cart'] });
  });

  it('shows why the last scheduled run made no analysis', async () => {
    GetDataRuns.mockResolvedValue({ runs: [
      { environment: 5, ran_at: '2026-10-28T08:00:00Z', outcome: 'empty', reason: 'not_important', detail: 'd', counts: {} },
    ] });
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    expect(await screen.findByText('dataCheck.reason.not_important')).toBeInTheDocument();
    expect(screen.getByText('dataCheck.outcome.empty')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: /Production/ })).toBeInTheDocument();
  });

  it('runs the check for the chosen environment and lists unlisted services in one click', async () => {
    CheckData.mockResolvedValue(report());
    const onFixed = vi.fn();
    render(<DataCheckPanel projectId={1} environments={ENVS} onFixed={onFixed} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    expect(await screen.findByText('dataCheck.diagnosis.unregistered_services')).toBeInTheDocument();
    expect(CheckData).toHaveBeenCalledWith(1, { environment: '5', minutes: 60 });
    expect(screen.getByText('dataCheck.step.services')).toBeInTheDocument();

    CheckData.mockResolvedValue(report({ diagnosis: { code: 'ok', message: 'ok', count: 3 }, fixes: [] }));
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.addServices' }));
    await waitFor(() => expect(ApplyDataFix).toHaveBeenCalledWith(1, { action: 'register_services', names: ['cart'] }));
    expect(onFixed).toHaveBeenCalled();
    expect(await screen.findByText('dataCheck.diagnosis.ok')).toBeInTheDocument();
  });

  it('offers the environment value the logs carry', async () => {
    CheckData.mockResolvedValue(report({
      stages: [{ key: 'found', count: 4 }, { key: 'project', count: 4 }, { key: 'environment', count: 0 }],
      diagnosis: { code: 'environment_not_tagged', message: 'm', environment: 'production' },
      fixes: [{ action: 'use_environment_label', environment: 5, value: 'live' }],
    }));
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    userEvent.click(await screen.findByRole('button', { name: 'dataCheck.useValue:live' }));
    await waitFor(() => expect(ApplyDataFix).toHaveBeenCalledWith(
      1, { action: 'use_environment_label', environment: 5, value: 'live' }));
  });

  it('checks production first', async () => {
    CheckData.mockResolvedValue(report());
    render(<DataCheckPanel projectId={1} environments={[
      { id: 3, name: 'development', display_name: 'Development' }, ...ENVS,
      { id: 7, name: 'staging', display_name: 'Staging' }]} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    await waitFor(() => expect(CheckData).toHaveBeenCalledWith(1, { environment: '5', minutes: 60 }));
  });

  it('names a few log locations and counts the rest', async () => {
    CheckData.mockResolvedValue(report({ locations: ['a', 'b', 'c', 'd', 'e', 'f'] }));
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    expect(await screen.findByText('dataCheck.step.found')).toBeInTheDocument();
  });

  it('maps the project onto how untagged logs are grouped, and removes the rule', async () => {
    CheckData.mockResolvedValue(report({
      seen: { project: [], environment: [], service: [], level: [], groupings: [
        { field: 'service.namespace', value: 'api', count: 12, matches_name: true },
        { field: 'kubernetes.namespace', value: 'kube-system', count: 40, matches_name: false },
      ] },
      fixes: [],
    }));
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    const use = await screen.findAllByRole('button', { name: 'dataCheck.groupings.use' });
    expect(use).toHaveLength(2);
    CheckData.mockResolvedValue(report({ project_rules: [{ field: 'service.namespace', value: 'api' }], fixes: [] }));
    userEvent.click(use[0]);
    await waitFor(() => expect(ApplyDataFix).toHaveBeenCalledWith(
      1, { action: 'add_project_rule', field: 'service.namespace', value: 'api' }));
    userEvent.click(await screen.findByRole('button', { name: 'common.remove' }));
    await waitFor(() => expect(ApplyDataFix).toHaveBeenLastCalledWith(
      1, { action: 'remove_project_rule', field: 'service.namespace', value: 'api' }));
  });

  it('shows counts at the sample cap as a minimum', async () => {
    CheckData.mockResolvedValue(report({ stages: [{ key: 'found', count: 1000, capped: true }] }));
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    expect(await screen.findByText('1000+')).toBeInTheDocument();
  });

  it('a viewer sees the last runs but neither the check nor the fixes', async () => {
    permissions = [];
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    expect(await screen.findByText('dataCheck.noPermission')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'dataCheck.run' })).not.toBeInTheDocument();
  });

  it('says what went wrong when the check cannot run', async () => {
    CheckData.mockRejectedValue({ response: { status: 404, data: { error: 'Environment not found' } } });
    render(<DataCheckPanel projectId={1} environments={ENVS} />);
    userEvent.click(screen.getByRole('button', { name: 'dataCheck.run' }));
    expect(await screen.findByText('Environment not found')).toBeInTheDocument();
  });
});
