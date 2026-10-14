import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

const registrationStatus = vi.fn();
vi.mock('../../services/auth.service', () => ({
  default: {
    registrationStatus: (...args) => registrationStatus(...args),
    login: vi.fn(),
    demoLogin: vi.fn(),
    password_forget: vi.fn(),
  },
}));
vi.mock('../../services/enterpriseSettings.service', () => ({
  default: { initSSO: vi.fn() },
}));

import Login from '../Login';

const renderAt = (path = '/login') =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Login />
    </MemoryRouter>,
  );

const status = (data) => registrationStatus.mockResolvedValue({ data });

describe('Login', () => {
  beforeEach(() => registrationStatus.mockReset());

  it('shows the password and SSO form on a normal install', async () => {
    status({ registration_enabled: false, demo_available: false, demo_only: false });
    renderAt();
    await waitFor(() => expect(registrationStatus).toHaveBeenCalled());
    expect(screen.getByLabelText('login.emailAddress')).toBeInTheDocument();
    expect(screen.getByText('login.loginWithSSO')).toBeInTheDocument();
    // No demo seeded: no button that would only 404.
    expect(screen.queryByText('login.tryDemo')).not.toBeInTheDocument();
  });

  it('offers the demo next to the form when one is seeded', async () => {
    status({ registration_enabled: false, demo_available: true, demo_only: false });
    renderAt();
    expect(await screen.findByText('login.tryDemo')).toBeInTheDocument();
    expect(screen.getByLabelText('login.emailAddress')).toBeInTheDocument();
  });

  it('shows only the demo on a demo-only host', async () => {
    status({ registration_enabled: false, demo_available: true, demo_only: true });
    renderAt();
    expect(await screen.findByText('login.demoOnlyTitle')).toBeInTheDocument();
    expect(screen.getByText('login.tryDemo')).toBeInTheDocument();
    expect(screen.queryByLabelText('login.emailAddress')).not.toBeInTheDocument();
    expect(screen.queryByText('login.loginWithSSO')).not.toBeInTheDocument();
  });

  it('explains a failed SSO sign-in', async () => {
    status({ registration_enabled: false, demo_available: false, demo_only: false });
    renderAt('/login?sso=failed');
    expect(await screen.findByText('login.ssoSignInFailed')).toBeInTheDocument();
  });
});
