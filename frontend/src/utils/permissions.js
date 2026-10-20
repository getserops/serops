/**
 * What the signed-in user may do, as the server says.
 *
 * The login and profile responses carry ``user.permissions`` (names such as
 * ``project.write``, defined in backend/Middlewares/rbac.py). The UI hides
 * controls the user can't use; the API enforces them either way. There is
 * no copy of the role table here: add a permission on the backend and the
 * UI picks it up.
 *
 *   const can = usePermissions();
 *   {can('project.delete') && <Button>Delete</Button>}
 */
import { useEffect, useState } from 'react';

const UPDATED_EVENT = 'serops:user-updated';

const readUser = () => {
    try {
        return JSON.parse(localStorage.getItem('user')) || {};
    } catch {
        return {};
    }
};

/** The stored user's permissions (empty when signed out or unknown). */
export const getPermissions = () => {
    const perms = readUser().permissions;
    return Array.isArray(perms) ? perms : [];
};

/** True when the signed-in user holds ``permission``. */
export const can = (permission) => getPermissions().includes(permission);

/**
 * Re-read the permissions from the server and store them: a role change, or
 * a session that started before the server sent permissions, takes effect
 * without signing out. Components using ``usePermissions`` re-render.
 */
export const refreshPermissions = async () => {
    try {
        const apiClient = (await import('../services/api-client')).default;
        const res = await apiClient.get('/auth/profile');
        const { role, permissions } = res?.data || {};
        if (!Array.isArray(permissions)) return;
        localStorage.setItem('user', JSON.stringify({ ...readUser(), role, permissions }));
        window.dispatchEvent(new Event(UPDATED_EVENT));
    } catch {
        /* keep what we have; the API still enforces every action */
    }
};

/** Hook: returns ``can`` and re-renders when the permissions change. */
export const usePermissions = () => {
    const [perms, setPerms] = useState(getPermissions);
    useEffect(() => {
        const onUpdate = () => setPerms(getPermissions());
        window.addEventListener(UPDATED_EVENT, onUpdate);
        return () => window.removeEventListener(UPDATED_EVENT, onUpdate);
    }, []);
    return (permission) => perms.includes(permission);
};

// =============================================================================
// ROLE DISPLAY HELPERS
// =============================================================================

export const ROLE_DISPLAY_NAMES = {
    admin: 'Admin',
    user: 'User',
    viewer: 'Viewer',
};

export const ROLE_COLORS = {
    admin: '#dc3545',      // red
    user: '#0d6efd',       // blue
    viewer: '#198754',     // green
};

export const getRoleDisplayName = (role) => ROLE_DISPLAY_NAMES[role] || role;
export const getRoleColor = (role) => ROLE_COLORS[role] || '#6c757d';
