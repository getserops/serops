/**
 * Role-Based Route Guards
 * 
 * Provides components for protecting routes based on user roles.
 * NOTE: This is for UX only - backend always enforces permissions.
 * 
 * Usage:
 *   import { ProtectedRoute, RoleGuard } from 'components/auth/RoleGuard';
 *   
 *   // Protect entire route
 *   <Route path="/settings" element={
 *     <ProtectedRoute requiredRole="admin">
 *       <Settings />
 *     </ProtectedRoute>
 *   } />
 *   
 *   // Conditionally show UI elements
 *   <RoleGuard requiredRole="user" fallback={<span>Upgrade to edit</span>}>
 *     <Button>Edit</Button>
 *   </RoleGuard>
 */

import React from 'react';
import { Navigate } from 'react-router-dom';
import { hasPermission, isUserOrAdmin, isAdmin } from '../../utils/permissions';

/**
 * Get the current user from localStorage
 */
const getCurrentUser = () => {
    try {
        return JSON.parse(localStorage.getItem('user')) || {};
    } catch {
        return {};
    }
};

/**
 * Check if user has minimum role level
 * @param {string} userRole - Current user's role
 * @param {string} requiredRole - Minimum required role
 */
const hasMinimumRole = (userRole, requiredRole) => {
    const roleHierarchy = { viewer: 0, user: 1, admin: 2 };
    const userLevel = roleHierarchy[userRole] ?? -1;
    const requiredLevel = roleHierarchy[requiredRole] ?? 0;
    return userLevel >= requiredLevel;
};

/**
 * ProtectedRoute - Redirect to dashboard if user doesn't have required role
 * 
 * @param {string} requiredRole - Minimum role required ('viewer', 'user', 'admin')
 * @param {string} redirectTo - Where to redirect if unauthorized (default: '/dashboard')
 * @param {ReactNode} children - Content to render if authorized
 */
export const ProtectedRoute = ({
    children,
    requiredRole = 'viewer',
    redirectTo = '/dashboard'
}) => {
    const user = getCurrentUser();
    const userRole = user.role || 'viewer';

    if (!hasMinimumRole(userRole, requiredRole)) {
        return <Navigate to={redirectTo} replace />;
    }

    return children;
};

/**
 * RoleGuard - Conditionally render content based on role
 * 
 * @param {string} requiredRole - Minimum role required
 * @param {ReactNode} fallback - Content to show if unauthorized (optional)
 * @param {ReactNode} children - Content to render if authorized
 */
export const RoleGuard = ({
    children,
    requiredRole = 'viewer',
    fallback = null
}) => {
    const user = getCurrentUser();
    const userRole = user.role || 'viewer';

    if (!hasMinimumRole(userRole, requiredRole)) {
        return fallback;
    }

    return children;
};

/**
 * AdminOnly - Shortcut for admin-only content
 */
export const AdminOnly = ({ children, fallback = null }) => (
    <RoleGuard requiredRole="admin" fallback={fallback}>
        {children}
    </RoleGuard>
);

/**
 * UserOrAdmin - Shortcut for user+ content (excludes viewers)
 */
export const UserOrAdmin = ({ children, fallback = null }) => (
    <RoleGuard requiredRole="user" fallback={fallback}>
        {children}
    </RoleGuard>
);

/**
 * Hook: useRole - Get current user's role and permissions
 */
export const useRole = () => {
    const user = getCurrentUser();
    const role = user.role || 'viewer';

    return {
        role,
        isAdmin: role === 'admin',
        isUser: role === 'user',
        isViewer: role === 'viewer',
        isUserOrAdmin: ['admin', 'user'].includes(role),
        hasMinimumRole: (required) => hasMinimumRole(role, required),
    };
};

export default ProtectedRoute;
