import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
const addSCMBinding = vi.fn();
const getRepos = vi.fn();
vi.mock('../../../services/project.service', () => ({
  ProjectService: { addSCMBinding: (...a) => addSCMBinding(...a), addCICDBinding: vi.fn(), deleteCICDBinding: vi.fn(), SyncSCMBinding: vi.fn(), SetupSCMWebhook: vi.fn() },
}));
vi.mock('../../../services/integration.service', () => ({
  IntegrationService: {
    getAll: vi.fn().mockResolvedValue([
      { id: 5, name: 'Acme GitHub', provider_type: 'github', is_active: true },
      { id: 3, name: 'Acme Jenkins', provider_type: 'jenkins', is_active: true },
    ]),
    getRepos: (...a) => getRepos(...a),
  },
}));

import ServiceDetailsModal from '../ServiceDetailsModal';

describe('ServiceDetailsModal — connect a repository later', () => {
  it('connects a repository to a service that has none', async () => {
    getRepos.mockResolvedValue([{ id: 144, full_name: 'acme/payments', html_url: 'https://github.com/acme/payments', default_branch: 'main' }]);
    addSCMBinding.mockResolvedValue({ id: 9 });
    const onRefresh = vi.fn();
    render(<ServiceDetailsModal show service={{ id: 7, name: 'payments', cicd_bindings: [] }} onHide={() => {}} onRefresh={onRefresh} />);
    userEvent.click(screen.getByRole('button', { name: /Connect repository/ }));
    const integration = await screen.findByRole('combobox', { name: 'Integration' });
    await waitFor(() => expect(integration.querySelectorAll('option').length).toBe(2));  // SCM integrations only
    userEvent.selectOptions(integration, '5');
    const repository = screen.getByRole('combobox', { name: 'Repository' });
    await waitFor(() => expect(repository.querySelectorAll('option').length).toBe(2));
    userEvent.selectOptions(repository, '144');
    userEvent.click(screen.getByRole('button', { name: 'Connect' }));
    expect(await screen.findByText('Repository connected.')).toBeInTheDocument();
    expect(addSCMBinding).toHaveBeenCalledWith(7, expect.objectContaining({
      integration: '5', repository_id: 144, repository_name: 'acme/payments', default_branch: 'main',
    }));
    expect(onRefresh).toHaveBeenCalled();
  });

  it('offers nothing to connect once a repository is linked', () => {
    render(<ServiceDetailsModal show service={{ id: 7, name: 'payments', cicd_bindings: [],
      scm_binding: { id: 1, provider_type: 'github', repository_name: 'acme/payments' } }} onHide={() => {}} />);
    expect(screen.queryByRole('button', { name: /Connect repository/ })).not.toBeInTheDocument();
  });
});
