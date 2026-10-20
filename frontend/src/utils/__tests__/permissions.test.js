import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { can, getPermissions, refreshPermissions, usePermissions } from '../permissions';

vi.mock('../../services/api-client', () => ({
    default: { get: vi.fn(async () => ({ data: { role: 'admin', permissions: ['project.read', 'project.delete'] } })) },
}));

const store = (user) => localStorage.setItem('user', JSON.stringify(user));

describe('permissions', () => {
    let data;

    beforeEach(() => {
        data = {};
        vi.stubGlobal('localStorage', {
            getItem: (key) => (key in data ? data[key] : null),
            setItem: (key, value) => { data[key] = String(value); },
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('reads the list the server sent', () => {
        store({ role: 'user', permissions: ['project.read', 'project.write'] });
        expect(can('project.write')).toBe(true);
        expect(can('project.delete')).toBe(false);
    });

    it('grants nothing when signed out, or for a session without a list', () => {
        expect(getPermissions()).toEqual([]);
        store({ role: 'admin' });
        expect(can('project.delete')).toBe(false);
    });

    it('refreshes from the profile and re-renders hook users', async () => {
        store({ role: 'viewer', permissions: ['project.read'], email: 'a@example.com' });
        const { result } = renderHook(() => usePermissions());
        expect(result.current('project.delete')).toBe(false);
        await act(() => refreshPermissions());
        expect(result.current('project.delete')).toBe(true);
        expect(JSON.parse(localStorage.getItem('user')).email).toBe('a@example.com');
    });
});
