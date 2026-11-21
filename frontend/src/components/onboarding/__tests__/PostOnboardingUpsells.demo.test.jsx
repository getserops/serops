import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../../../services/api-client', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
}));

import apiClient from '../../../services/api-client';
import PostOnboardingUpsells from '../PostOnboardingUpsells';

const signIn = (user) => window.localStorage.getItem.mockImplementation(
  (k) => (k === 'user' ? JSON.stringify(user) : null),
);

describe('PostOnboardingUpsells', () => {
  beforeEach(() => { window.localStorage.getItem.mockReset(); apiClient.get.mockClear(); });

  it('asks an organisation with no bindings to connect source control and CI/CD', async () => {
    signIn({ is_demo: false });
    render(<PostOnboardingUpsells />);
    expect(await screen.findByText(/source-control integration/i)).toBeInTheDocument();
    expect(screen.getByText(/CI\/CD integration/i)).toBeInTheDocument();
  });

  it('shows nothing to a demo visitor, who cannot connect anything', async () => {
    signIn({ is_demo: true });
    const { container } = render(<PostOnboardingUpsells />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(screen.queryByText(/source-control integration/i)).toBeNull();
  });
});
