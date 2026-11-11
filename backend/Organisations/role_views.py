"""
The organisation's roles: built-in (viewer, user, admin) and custom.

Listing is Community: the Users and Security pages show and keep the roles
members already have. Creating, editing and deleting custom roles is
Enterprise (``ee/access/roles.py``, ``/api/ee/roles/``).
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Middlewares.rbac import (ALWAYS_GRANTED, ASSIGNABLE_PERMISSIONS, BUILTIN_ROLES, IMPLIES, PERMISSIONS,
                              ROLE_PERMISSIONS, Requires)
from Users.models import CustomRole, SecuritySettings, User

BUILTIN_NAMES = {'viewer': 'Viewer', 'user': 'User', 'admin': 'Admin'}


def serialize_role(role, member_count=None):
    data = {
        'id': role.pk, 'key': role.key, 'name': role.name, 'description': role.description,
        'permissions': sorted(role.permissions or []),
    }
    if member_count is not None:
        data['member_count'] = member_count
    return data


def sso_references(role):
    """Whether an SSO rule or the SSO default role names this role."""
    sec = SecuritySettings.objects.filter(organisation_id=role.organisation_id).first()
    if sec is None:
        return False
    return sec.sso_default_role == role.key or any(r.get('role') == role.key for r in sec.sso_role_mappings or [])


class RoleListView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='org.read')]

    def get(self, request):
        org = request.user.organisation
        roles = CustomRole.objects.filter(organisation=org)
        counts = {}
        for role_id in User.objects.filter(organisation=org, role='custom').values_list('custom_role_id', flat=True):
            counts[role_id] = counts.get(role_id, 0) + 1
        return Response({
            'builtin': [{'key': k, 'name': BUILTIN_NAMES[k], 'permissions': sorted(ROLE_PERMISSIONS[k])}
                        for k in BUILTIN_ROLES],
            'custom': [serialize_role(r, counts.get(r.pk, 0)) for r in roles],
            'catalogue': [{'code': c, 'description': PERMISSIONS[c]} for c in PERMISSIONS
                          if c in ASSIGNABLE_PERMISSIONS],
            'always_granted': sorted(ALWAYS_GRANTED),
            'implies': IMPLIES,
        })
