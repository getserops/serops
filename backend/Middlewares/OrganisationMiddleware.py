from rest_framework.permissions import BasePermission
from django.http import HttpResponseForbidden

class OrganisationsPermissions(BasePermission):
    allowed_roles = ["admin"]

    def has_permission(self, request, view):
        user_role = request.user.role if hasattr(request.user, 'role') else None
        return user_role in self.allowed_roles
