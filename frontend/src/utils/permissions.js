/**
 * RBAC Permission System - Frontend Helper
 * 
 * Mirrors the backend permission system for UI visibility control.
 * NOTE: This is for UX only - backend always enforces permissions.
 * 
 * Usage:
 *   import { permissions, hasPermission, canManageProjects } from 'utils/permissions';
 *   
 *   // Check specific permission
 *   if (hasPermission(user.role, 'project.create')) { ... }
 *   
 *   // Use helper functions
 *   {canManageProjects(user.role) && <Button>Add Project</Button>}
 */

// Permission codes (must match backend Permissions class)
export const Permissions = {
    // Projects
    PROJECT_CREATE: 'project.create',
    PROJECT_READ: 'project.read',
    PROJECT_UPDATE: 'project.update',
    PROJECT_DELETE: 'project.delete',

    // Services
    SERVICE_CREATE: 'service.create',
    SERVICE_READ: 'service.read',
    SERVICE_UPDATE: 'service.update',
    SERVICE_DELETE: 'service.delete',
    SERVICE_WEBHOOK: 'service.webhook',

    // Data / Batches
    BATCH_READ: 'batch.read',
    BATCH_DELETE: 'batch.delete',
    BATCH_EXPORT: 'batch.export',
    BATCH_ANALYZE: 'batch.analyze',

    // Issues (AI-generated, not user-created)
    ISSUE_READ: 'issue.read',
    ISSUE_UPDATE: 'issue.update',
    ISSUE_DELETE: 'issue.delete',

    // Users
    USER_INVITE: 'user.invite',
    USER_READ: 'user.read',
    USER_UPDATE: 'user.update',
    USER_DELETE: 'user.delete',
    USER_ROLE_CHANGE: 'user.role_change',

    // Settings
    SETTINGS_READ: 'settings.read',
    SETTINGS_UPDATE: 'settings.update',

    // Chat
    CHAT_USE: 'chat.use',
};

// Role-Permission Matrix (mirrors backend ROLE_PERMISSIONS)
const ROLE_PERMISSIONS = {
    admin: [
        // Full access to everything
        Permissions.PROJECT_CREATE, Permissions.PROJECT_READ,
        Permissions.PROJECT_UPDATE, Permissions.PROJECT_DELETE,
        Permissions.SERVICE_CREATE, Permissions.SERVICE_READ,
        Permissions.SERVICE_UPDATE, Permissions.SERVICE_DELETE,
        Permissions.SERVICE_WEBHOOK,
        Permissions.BATCH_READ, Permissions.BATCH_DELETE,
        Permissions.BATCH_EXPORT, Permissions.BATCH_ANALYZE,
        Permissions.ISSUE_READ, Permissions.ISSUE_UPDATE, Permissions.ISSUE_DELETE,
        Permissions.USER_INVITE, Permissions.USER_READ,
        Permissions.USER_UPDATE, Permissions.USER_DELETE,
        Permissions.USER_ROLE_CHANGE,
        Permissions.SETTINGS_READ, Permissions.SETTINGS_UPDATE,
        Permissions.CHAT_USE,
    ],

    // 'user' role: Engineers with write access
    user: [
        // Projects - Create/Read/Update (no delete)
        Permissions.PROJECT_CREATE, Permissions.PROJECT_READ,
        Permissions.PROJECT_UPDATE,
        // Services - Full access except delete
        Permissions.SERVICE_CREATE, Permissions.SERVICE_READ,
        Permissions.SERVICE_UPDATE,
        Permissions.SERVICE_WEBHOOK,
        // Data - Read + Export + Analyze (no delete)
        Permissions.BATCH_READ, Permissions.BATCH_EXPORT,
        Permissions.BATCH_ANALYZE,
        // Issues - Read + Update (acknowledge, no delete)
        Permissions.ISSUE_READ, Permissions.ISSUE_UPDATE,
        // Users - Read only (can see team members)
        Permissions.USER_READ,
        // Settings - Read only
        Permissions.SETTINGS_READ,
        // Chat
        Permissions.CHAT_USE,
    ],

    // 'viewer' role: Read-only for stakeholders, SOC analysts, auditors
    viewer: [
        // Projects - Read only
        Permissions.PROJECT_READ,
        // Services - Read only
        Permissions.SERVICE_READ,
        // Data - Read only (no analyze, no export)
        Permissions.BATCH_READ,
        // Issues - Read only
        Permissions.ISSUE_READ,
        // Chat - Can use for querying
        Permissions.CHAT_USE,
    ],
};

/**
 * Check if a role has a specific permission
 * @param {string} role - User role ('admin', 'user', 'viewer')
 * @param {string} permission - Permission code (e.g., 'project.create')
 * @returns {boolean}
 */
export const hasPermission = (role, permission) => {
    if (!role || !ROLE_PERMISSIONS[role]) {
        return false;
    }
    return ROLE_PERMISSIONS[role].includes(permission);
};

/**
 * Get all permissions for a role
 * @param {string} role 
 * @returns {string[]}
 */
export const getPermissions = (role) => {
    return ROLE_PERMISSIONS[role] || [];
};

// =============================================================================
// CONVENIENCE HELPERS
// =============================================================================

// Projects
export const canCreateProjects = (role) => hasPermission(role, Permissions.PROJECT_CREATE);
export const canEditProjects = (role) => hasPermission(role, Permissions.PROJECT_UPDATE);
export const canDeleteProjects = (role) => hasPermission(role, Permissions.PROJECT_DELETE);
export const canManageProjects = (role) => canCreateProjects(role) || canEditProjects(role);

// Services
export const canCreateServices = (role) => hasPermission(role, Permissions.SERVICE_CREATE);
export const canDeleteServices = (role) => hasPermission(role, Permissions.SERVICE_DELETE);
export const canSetupWebhooks = (role) => hasPermission(role, Permissions.SERVICE_WEBHOOK);

// Data
export const canDeleteBatches = (role) => hasPermission(role, Permissions.BATCH_DELETE);
export const canExportData = (role) => hasPermission(role, Permissions.BATCH_EXPORT);

// Issues
export const canUpdateIssues = (role) => hasPermission(role, Permissions.ISSUE_UPDATE);
export const canDeleteIssues = (role) => hasPermission(role, Permissions.ISSUE_DELETE);

// Users
export const canManageUsers = (role) => hasPermission(role, Permissions.USER_INVITE);
export const canInviteUsers = (role) => hasPermission(role, Permissions.USER_INVITE);
export const canChangeRoles = (role) => hasPermission(role, Permissions.USER_ROLE_CHANGE);

// Settings
export const canEditSettings = (role) => hasPermission(role, Permissions.SETTINGS_UPDATE);
export const canViewSettings = (role) => hasPermission(role, Permissions.SETTINGS_READ);

// Role checks
export const isAdmin = (role) => role === 'admin';
export const isUserOrAdmin = (role) => ['admin', 'user'].includes(role);
export const isViewer = (role) => role === 'viewer';

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

