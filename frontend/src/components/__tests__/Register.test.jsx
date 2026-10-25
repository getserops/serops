import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Routes, Route } from 'react-router-dom';

// A plain function, not a vi.fn: vitest reports a rejected promise returned
// by a spy as a test failure even when the component catches it.
let registerImpl = async () => ({ data: {} });
vi.mock('../../services/auth.service', () => ({ default: { register: (...a) => registerImpl(...a) } }));

import Register from '../Register';
import RegisterPart3 from '../RegisterPart3';

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
  userEvent.type(screen.getByLabelText('First Name'), 'Ada');
  userEvent.type(screen.getByLabelText('Last Name'), 'Admin');
  userEvent.type(screen.getByLabelText('Work Email'), 'ada@acme.test');
  userEvent.type(screen.getByLabelText('Company Name'), 'Acme');
  userEvent.click(screen.getByRole('button', { name: /Continue/ }));
  userEvent.type(await screen.findByLabelText('Password'), 'Str0ngPassw0rd');
  userEvent.type(screen.getByLabelText('Confirm Password'), 'Str0ngPassw0rd');
  userEvent.click(screen.getByRole('button', { name: 'Create Account' }));
};

describe('Register', () => {
  beforeEach(() => { registerImpl = async () => ({ data: {} }); });

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
});
