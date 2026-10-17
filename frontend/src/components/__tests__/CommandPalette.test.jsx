import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';

const navigate = vi.fn();
vi.mock('react-router-dom', () => ({ useNavigate: () => navigate }));
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: { projects: [{ id: 4, name: 'acme-checkout' }] } }) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => ({ 'nav.issues': 'Issues', 'nav.dashboard': 'Dashboard', 'auditLog.title': 'Audit Log' }[k] || k) }) }));
vi.mock('../../services/data.service', () => ({ default: { getIssues: vi.fn() } }));
vi.mock('../../services/investigation.service', () => ({ default: { options: vi.fn() } }));
vi.mock('../../utils/demo', () => ({ isDemoUser: () => false }));

import CommandPalette from '../CommandPalette';

describe('CommandPalette', () => {
  it('opens on Ctrl+K, filters, and navigates on Enter', () => {
    render(<CommandPalette />);
    expect(screen.queryByRole('combobox')).toBeNull();
    act(() => { fireEvent.keyDown(window, { key: 'k', ctrlKey: true }); });
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'audit' } });
    const options = screen.getAllByRole('option');
    expect(options[0].textContent).toContain('Audit Log');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(navigate).toHaveBeenCalledWith('/dash/settings/audit');
  });

  it('finds projects by name', () => {
    render(<CommandPalette />);
    act(() => { fireEvent.keyDown(window, { key: 'k', metaKey: true }); });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'checkout' } });
    fireEvent.click(screen.getByText('acme-checkout'));
    expect(navigate).toHaveBeenCalledWith('/dash/projects/4');
  });
});
