import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

// The real English strings, with {{values}} filled in, so the test reads
// what a person reads.
const translate = (dict) => (key, opts = {}) => {
  const text = key.split('.').reduce((o, k) => o?.[k], dict);
  if (typeof text !== 'string') return opts.defaultValue ?? key;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
let locale = en;
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate(locale) }) }));

// A plain function, not a vi.fn: vitest reports a rejected promise returned
// by a spy as a test failure even when the component catches it.
let registerImpl = async () => ({ data: {} });
let statusImpl = async () => ({ data: { registration_enabled: true } });
vi.mock('../../services/auth.service', () => ({
  default: { register: (...a) => registerImpl(...a), registrationStatus: (...a) => statusImpl(...a) },
}));

import Register from '../Register';
import RegisterPart3 from '../RegisterPart3';

const renderAt = (path = '/register') => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes>
      <Route path="/register" element={<Register />} />
      <Route path="/login" element={<p>login page</p>} />
    </Routes>
  </MemoryRouter>,
);

const fillAndSubmit = async () => {
  render(
    <MemoryRouter initialEntries={['/register']}>
      <Routes>
        <Route path="/register" element={<Register />} />
        <Route path="/register_verif" element={<RegisterPart3 />} />
        <Route path="/login" element={<p>login page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  // Labels are linked to their inputs (journey suite, A1).
  userEvent.type(await screen.findByLabelText('First Name'), 'Ada');
  userEvent.type(screen.getByLabelText('Last Name'), 'Admin');
  userEvent.type(screen.getByLabelText('Work Email'), 'ada@acme.test');
  userEvent.type(screen.getByLabelText('Company Name'), 'Acme');
  userEvent.click(screen.getByRole('button', { name: /Continue/ }));
  userEvent.type(await screen.findByLabelText('Password'), 'Str0ngPassw0rd');
  userEvent.type(screen.getByLabelText('Confirm Password'), 'Str0ngPassw0rd');
  userEvent.click(screen.getByRole('button', { name: 'Create Account' }));
};

describe('Register', () => {
  beforeEach(() => {
    locale = en;
    registerImpl = async () => ({ data: {} });
    statusImpl = async () => ({ data: { registration_enabled: true } });
  });

  it('says to check the email after an emailed sign-up (B1)', async () => {
    registerImpl = async () => ({ data: { email_sent: true, message: 'Registration successful!' } });
    await fillAndSubmit();
    expect(await screen.findByRole('heading', { name: 'Verify by email' })).toBeInTheDocument();
    expect(screen.getByText('ada@acme.test')).toBeInTheDocument();
  });

  it('says when the activation email could not be sent (B11)', async () => {
    registerImpl = async () => ({ data: { email_sent: false, message: 'Your account was created, but the activation email could not be sent.' } });
    await fillAndSubmit();
    expect(await screen.findByRole('heading', { name: 'Account created, email not sent' })).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('could not be sent');
  });

  it('explains a rate-limited sign-up (B7)', async () => {
    const throttled = Object.assign(new Error('Request failed with status code 429'),
      { response: { status: 429, data: { detail: 'Request was throttled. Expected available in 120 seconds.' } } });
    registerImpl = () => Promise.reject(throttled);
    await fillAndSubmit();
    expect(await screen.findByText('Too many attempts. Try again in 2 minutes.')).toBeInTheDocument();
  });

  // 1.5.6: once the first organisation existed the server refused sign-ups,
  // but the page showed the form and the visitor learnt it at the last step.
  it('says sign-up is closed and offers sign-in, with no form', async () => {
    statusImpl = async () => ({ data: { registration_enabled: false } });
    renderAt();
    expect(await screen.findByRole('heading', { name: 'Sign-up is closed' })).toBeInTheDocument();
    expect(screen.getByText(/does not accept new registrations/)).toBeInTheDocument();
    expect(screen.queryByLabelText('First Name')).toBeNull();
    expect(screen.queryByRole('button', { name: /Continue/ })).toBeNull();
    await userEvent.click(screen.getByRole('link', { name: 'Sign In' }));
    expect(await screen.findByText('login page')).toBeInTheDocument();
  });

  it('says so in French too', async () => {
    locale = fr;
    statusImpl = async () => ({ data: { registration_enabled: false } });
    renderAt();
    expect(await screen.findByRole('heading', { name: 'Les inscriptions sont fermées' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: fr.login.signIn })).toHaveAttribute('href', '/login');
  });

  it('shows the form when the status cannot be read', async () => {
    statusImpl = () => Promise.reject(new Error('Network Error'));
    renderAt();
    expect(await screen.findByLabelText('First Name')).toBeInTheDocument();
  });

  it('shows the form when the status does not come', async () => {
    vi.useFakeTimers();
    try {
      statusImpl = () => new Promise(() => {});
      renderAt();
      expect(screen.queryByLabelText('First Name')).toBeNull();
      await act(async () => { vi.advanceTimersByTime(4000); });
      expect(screen.getByLabelText('First Name')).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
