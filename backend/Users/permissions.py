"""
Role-Based Access Control (RBAC) Permissions

Provides decorators and utilities for enforcing role-based permissions.

Role Hierarchy:
    viewer < user < admin

Permission Levels:
    - viewer: Read-only access to dashboards, logs, issues, code changes
    - user: viewer + trigger analysis, chat, acknowledge issues  
    - admin: user + settings, team management, integrations, billing
"""

from functools import wraps
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)

# Role hierarchy (higher index = more permissions)
ROLE_HIERARCHY = {
    'viewer': 0,
    'user': 1,
    'admin': 2,
}

# Minimum role required for each action type
ACTION_PERMISSIONS = {
    # Read operations (viewer+)
    'view_dashboard': 'viewer',
    'view_batches': 'viewer',
    'view_issues': 'viewer',
    'view_logs': 'viewer',
    'view_code_changes': 'viewer',
    'view_metrics': 'viewer',
    
    # Write operations (user+)
    'trigger_analysis': 'user',
    'use_chat': 'user',
    'acknowledge_issue': 'user',
    'create_batch': 'user',
    
    # Admin operations (admin only)
    'manage_team': 'admin',
    'manage_settings': 'admin',
    'manage_integrations': 'admin',
    'manage_projects': 'admin',
    'delete_data': 'admin',
    'view_audit_logs': 'admin',
}


def has_role(user, required_role):
    """
    Check if user has at least the required role level.
    
    Args:
        user: User instance
        required_role: Minimum role required ('viewer', 'user', or 'admin')
    
    Returns:
        bool: True if user has sufficient permissions
    """
    if not user or not user.is_authenticated:
        return False
    
    user_role = getattr(user, 'role', 'viewer')
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    
    return user_level >= required_level


def can_perform(user, action):
    """
    Check if user can perform a specific action.
    
    Args:
        user: User instance
        action: Action key from ACTION_PERMISSIONS
    
    Returns:
        bool: True if user can perform the action
    """
    required_role = ACTION_PERMISSIONS.get(action, 'admin')  # Default to admin if unknown
    return has_role(user, required_role)


def require_role(min_role):
    """
    Decorator to require minimum role for a view.
    
    Usage:
        @require_role('admin')
        def my_admin_view(request):
            ...
        
        @require_role('user')  
        def my_user_view(request):
            ...
    
    Args:
        min_role: Minimum role required ('viewer', 'user', or 'admin')
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(self, request, *args, **kwargs):
            if not has_role(request.user, min_role):
                user_role = getattr(request.user, 'role', 'unknown')
                logger.warning(
                    f"Permission denied: user '{request.user.email}' with role '{user_role}' "
                    f"attempted to access {view_func.__name__} (requires: {min_role})"
                )
                return Response(
                    {
                        'error': 'Permission denied',
                        'message': f'This action requires {min_role} role or higher',
                        'required_role': min_role,
                        'current_role': user_role,
                    },
                    status=status.HTTP_403_FORBIDDEN
                )
            return view_func(self, request, *args, **kwargs)
        return wrapper
    return decorator


def require_action(action):
    """
    Decorator to require permission for a specific action.
    
    Usage:
        @require_action('manage_settings')
        def settings_view(request):
            ...
    
    Args:
        action: Action key from ACTION_PERMISSIONS
    """
    required_role = ACTION_PERMISSIONS.get(action, 'admin')
    return require_role(required_role)


class RolePermissionMixin:
    """
    Mixin for class-based views to add role-based permission checks.
    
    Usage:
        class MyView(RolePermissionMixin, APIView):
            required_role = 'admin'
            
            def get(self, request):
                ...
    """
    required_role = 'viewer'  # Default to most restrictive read-only
    
    def check_permissions(self, request):
        super().check_permissions(request)
        
        if not has_role(request.user, self.required_role):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(
                detail=f'This action requires {self.required_role} role or higher'
            )


def get_user_permissions(user):
    """
    Get all permissions for a user based on their role.
    
    Returns:
        dict: {action: bool} for all defined actions
    """
    return {
        action: can_perform(user, action)
        for action in ACTION_PERMISSIONS
    }
