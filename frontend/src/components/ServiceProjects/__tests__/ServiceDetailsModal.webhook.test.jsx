import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key) => key }) }));
const addCICDBinding = vi.fn();
vi.mock('../../../services/project.service', () => ({
  ProjectService: { addCICDBinding: (...a) => addCICDBinding(...a), deleteCICDBinding: vi.fn(), SyncSCMBinding: vi.fn(), SetupSCMWebhook: vi.fn() },
}));
vi.mock('../../../services/integration.service', () => ({
  IntegrationService: { getAll: vi.fn().mockResolvedValue([
    { id: 3, name: 'Acme Jenkins', provider_type: 'jenkins', is_active: true },
    { id: 4, name: 'Argo CD prod', provider_type: 'argocd', is_active: true },
  ]) },
}));

import ServiceDetailsModal from '../ServiceDetailsModal';

describe('ServiceDetailsModal — webhook secret', () => {
  it('shows the new binding\'s webhook URLs and secret once, after adding a pipeline', async () => {
    addCICDBinding.mockResolvedValue({ id: 12, webhook_secret: 'whsec-123' });
    render(<ServiceDetailsModal show service={{ id: 7, name: 'payments', cicd_bindings: [] }} onHide={() => {}} />);
    userEvent.click(screen.getByRole('button', { name: /Add Pipeline/ }));
    const [integration, type] = await screen.findAllByRole('combobox');
    await waitFor(() => expect(integration.querySelectorAll('option').length).toBeGreaterThan(1));
    userEvent.selectOptions(integration, '3');
    userEvent.selectOptions(type, 'deploy');
    userEvent.type(screen.getByPlaceholderText('e.g., job/my-job'), 'payments-deploy');
    userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByDisplayValue('whsec-123')).toBeInTheDocument();
    expect(screen.getByText(/\/api\/webhooks\/jenkins\/12\/$/)).toBeInTheDocument();
    expect(screen.getByText(/\/api\/providers\/webhook\/argocd\/12\/$/)).toBeInTheDocument();
  });

  it('an Argo CD integration binds as a deployment and shows only the Argo CD webhook', async () => {
    addCICDBinding.mockReset();
    addCICDBinding.mockResolvedValue({ id: 13, webhook_secret: 'whsec-456' });
    render(<ServiceDetailsModal show service={{ id: 7, name: 'payments', cicd_bindings: [] }} onHide={() => {}} />);
    userEvent.click(screen.getByRole('button', { name: /Add Pipeline/ }));
    const integration = await screen.findByRole('combobox', { name: 'Integration' });
    await waitFor(() => expect(integration.querySelectorAll('option').length).toBeGreaterThan(2));
    userEvent.selectOptions(integration, '4');
    expect(screen.getByRole('combobox', { name: 'Type' })).toHaveValue('deploy');
    userEvent.type(screen.getByRole('textbox', { name: 'Application' }), 'payments');
    userEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByDisplayValue('whsec-456')).toBeInTheDocument();
    expect(screen.getByText(/\/api\/providers\/webhook\/argocd\/13\/$/)).toBeInTheDocument();
    expect(screen.queryByText(/\/api\/providers\/webhook\/flux\//)).not.toBeInTheDocument();
  });
});
