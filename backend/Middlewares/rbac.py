"""
RBAC Permission System - Option 1 (Hardcoded)

This module provides role-based access control with a clean abstraction layer.
Designed for easy migration to Option 2 (database-managed) in the future.

Usage:
    from Middlewares.rbac import has_permission, RBACPermission
    
    # In views:
    class ProjectViewSet(viewsets.ModelViewSet):
        permission_classes = [IsAuthenticated, RBACPermission('project.create')]
    
    # In code:
    if has_permission(request.user, 'project.delete'):
        project.delete()
"""

from rest_framework.permissions import BasePermission
from functools import wraps


# =============================================================================
# PERMISSION DEFINITIONS
# =============================================================================

class Permissions:
    """All available permissions in the system.
    
    Naming convention: {resource}.{action}
    """
    # Projects
    PROJECT_CREATE = 'project.create'
    PROJECT_READ = 'project.read'
    PROJECT_UPDATE = 'project.update'
    PROJECT_DELETE = 'project.delete'
    
    # Services
    SERVICE_CREATE = 'service.create'
    SERVICE_READ = 'service.read'
    SERVICE_UPDATE = 'service.update'
    SERVICE_DELETE = 'service.delete'
    SERVICE_WEBHOOK = 'service.webhook'
    
    # Data / Batches
    BATCH_READ = 'batch.read'
    BATCH_DELETE = 'batch.delete'
    BATCH_EXPORT = 'batch.export'
    BATCH_ANALYZE = 'batch.analyze'
    
    # Issues (AI-generated, not user-created)
    ISSUE_READ = 'issue.read'
    ISSUE_UPDATE = 'issue.update'  # Mark as resolved/acknowledged
    ISSUE_DELETE = 'issue.delete'
    
    # Users
    USER_INVITE = 'user.invite'
    USER_READ = 'user.read'
    USER_UPDATE = 'user.update'
    USER_DELETE = 'user.delete'
    USER_ROLE_CHANGE = 'user.role_change'
    
    # Settings
    SETTINGS_READ = 'settings.read'
    SETTINGS_UPDATE = 'settings.update'
    
    # Chat
    CHAT_USE = 'chat.use'


# =============================================================================
# ROLE-PERMISSION MATRIX
# =============================================================================

ROLE_PERMISSIONS = {
    'admin': [
        # Projects - Full access
        Permissions.PROJECT_CREATE,
        Permissions.PROJECT_READ,
        Permissions.PROJECT_UPDATE,
        Permissions.PROJECT_DELETE,
        
        # Services - Full access
        Permissions.SERVICE_CREATE,
        Permissions.SERVICE_READ,
        Permissions.SERVICE_UPDATE,
        Permissions.SERVICE_DELETE,
        Permissions.SERVICE_WEBHOOK,
        
        # Data - Full access
        Permissions.BATCH_READ,
        Permissions.BATCH_DELETE,
        Permissions.BATCH_EXPORT,
        Permissions.BATCH_ANALYZE,
        
        # Issues - Full access (AI-generated, manage only)
        Permissions.ISSUE_READ,
        Permissions.ISSUE_UPDATE,
        Permissions.ISSUE_DELETE,
        
        # Users - Full access
        Permissions.USER_INVITE,
        Permissions.USER_READ,
        Permissions.USER_UPDATE,
        Permissions.USER_DELETE,
        Permissions.USER_ROLE_CHANGE,
        
        # Settings - Full access
        Permissions.SETTINGS_READ,
        Permissions.SETTINGS_UPDATE,
        
        # Chat
        Permissions.CHAT_USE,
    ],
    
    # 'user' role: Engineers (merged devops + developer with write access)
    'user': [
        # Projects - Create/Read/Update (no delete)
        Permissions.PROJECT_CREATE,
        Permissions.PROJECT_READ,
        Permissions.PROJECT_UPDATE,
        
        # Services - Full access except delete
        Permissions.SERVICE_CREATE,
        Permissions.SERVICE_READ,
        Permissions.SERVICE_UPDATE,
        Permissions.SERVICE_WEBHOOK,
        
        # Data - Read + Export + Analyze (no delete)
        Permissions.BATCH_READ,
        Permissions.BATCH_EXPORT,
        Permissions.BATCH_ANALYZE,
        
        # Issues - Read + Update (acknowledge, no delete)
        Permissions.ISSUE_READ,
        Permissions.ISSUE_UPDATE,
        
        # Users - Read only (can see team members)
        Permissions.USER_READ,
        
        # Settings - Read only
        Permissions.SETTINGS_READ,
        
        # Chat
        Permissions.CHAT_USE,
    ],
    
    # 'viewer' role: Read-only for stakeholders, SOC analysts, auditors
    'viewer': [
        # Projects - Read only
        Permissions.PROJECT_READ,
        
        # Services - Read only
        Permissions.SERVICE_READ,
        
        # Data - Read only (no analyze, no export)
        Permissions.BATCH_READ,
        
        # Issues - Read only
        Permissions.ISSUE_READ,
        
        # Users - None (can only see self via profile)
        
        # Settings - None
        
        # Chat - Can use for querying (read-like operation)
        Permissions.CHAT_USE,
    ],
}


# =============================================================================
# PERMISSION CHECKING (Abstraction Layer)
# =============================================================================

class PermissionBackend:
    """
    Abstract permission backend.
    
    Option 1: Uses ROLE_PERMISSIONS dict (current)
    Option 2: Would query database (future)
    
    To migrate to Option 2, replace this class implementation.
    """
    
    @staticmethod
    def get_permissions_for_role(role: str, organisation=None) -> list:
        """
        Get all permissions for a given role.
        
        Args:
            role: User role ('admin', 'user', 'viewer')
            organisation: Optional org for future per-org customization
        
        Returns:
            List of permission codes
        """
        # Option 1: Return from dict
        return ROLE_PERMISSIONS.get(role, [])
        
        # Option 2 (future): Query database
        # return list(
        #     RolePermission.objects
        #     .filter(role=role, organisation=organisation)
        #     .values_list('permission__code', flat=True)
        # )
    
    @staticmethod
    def has_permission(user, permission_code: str) -> bool:
        """
        Check if user has a specific permission.
        
        Args:
            user: Django User instance
            permission_code: Permission to check (e.g., 'project.create')
        
        Returns:
            True if user has permission, False otherwise
        """
        if not user or not user.is_authenticated:
            return False
        
        role = getattr(user, 'role', None)
        if not role:
            return False
        
        permissions = PermissionBackend.get_permissions_for_role(
            role, 
            getattr(user, 'organisation', None)
        )
        return permission_code in permissions


# =============================================================================
# PUBLIC API
# =============================================================================

def has_permission(user, permission_code: str) -> bool:
    """
    Check if user has a specific permission.
    
    Usage:
        if has_permission(request.user, 'project.delete'):
            project.delete()
    """
    return PermissionBackend.has_permission(user, permission_code)


def get_user_permissions(user) -> list:
    """
    Get all permissions for a user.
    
    Usage:
        permissions = get_user_permissions(request.user)
        # ['project.read', 'batch.read', ...]
    """
    if not user or not user.is_authenticated:
        return []
    
    role = getattr(user, 'role', None)
    return PermissionBackend.get_permissions_for_role(
        role,
        getattr(user, 'organisation', None)
    )


# =============================================================================
# DRF PERMISSION CLASSES
# =============================================================================

class RBACPermission(BasePermission):
    """
    DRF Permission class that checks for a specific permission.
    
    Usage:
        class ProjectViewSet(viewsets.ModelViewSet):
            permission_classes = [IsAuthenticated, RBACPermission('project.create')]
    """
    
    def __init__(self, required_permission: str):
        self.required_permission = required_permission
    
    def has_permission(self, request, view):
        return has_permission(request.user, self.required_permission)
    
    def __call__(self):
        """Allow usage as permission_classes = [RBACPermission('project.create')]"""
        return self


def require_permission(permission_code: str):
    """
    Factory function to create permission class for DRF.
    
    Usage:
        permission_classes = [IsAuthenticated, require_permission('project.create')]
    """
    class DynamicPermission(BasePermission):
        def has_permission(self, request, view):
            return has_permission(request.user, permission_code)
    
    return DynamicPermission


class IsAdminRole(BasePermission):
    """Only users with admin role."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            getattr(request.user, 'role', None) == 'admin'
        )


class IsUserOrAdmin(BasePermission):
    """Users with admin or user role (excludes viewer)."""
    
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and 
            getattr(request.user, 'role', None) in ['admin', 'user']
        )


class ReadOnlyForViewer(BasePermission):
    """
    - Admin/User: Full access
    - Viewer: Read-only (GET, HEAD, OPTIONS)
    """
    SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
    
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        
        role = getattr(request.user, 'role', None)
        
        if role in ['admin', 'user']:
            return True
        
        return request.method in self.SAFE_METHODS


class SameOrganisation(BasePermission):
    """
    Ensure user can only access objects in their organisation.
    
    Works with objects that have either:
    - .organisation FK
    - .project.organisation FK
    """
    
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return False
        
        # Direct organisation reference
        if hasattr(obj, 'organisation'):
            return obj.organisation == user_org
        
        # Via project
        if hasattr(obj, 'project') and hasattr(obj.project, 'organisation'):
            return obj.project.organisation == user_org
        
        # No org reference, allow (or deny based on your preference)
        return True


# =============================================================================
# DECORATOR FOR FUNCTION-BASED VIEWS
# =============================================================================

def permission_required(permission_code: str):
    """
    Decorator for function-based views.
    
    Usage:
        @api_view(['POST'])
        @permission_required('project.delete')
        def delete_project(request, project_id):
            ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not has_permission(request.user, permission_code):
                from rest_framework.response import Response
                from rest_framework import status
                return Response(
                    {'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator
