"""
Custom roles (Enterprise, feature ``custom_roles``): create, edit, delete.

A member only creates or edits a role whose permissions they hold
(``can_grant``); a role still assigned to someone, or named by an SSO rule,
can't be deleted. Without the license, roles that exist keep working and can
still be deleted, so an organisation can always go back to built-in roles.
"""
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.rbac import BUILTIN_ROLES, Requires, can_grant, normalise_permissions
from Organisations.role_views import BUILTIN_NAMES, serialize_role, sso_references
from Users.models import CustomRole
from Utils import edition

FEATURE = 'custom_roles'


def _unlicensed():
    if edition.has_feature(FEATURE):
        return None
    return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)


class RoleCreateView(APIView):
    permission_classes = [IsAuthenticated, Requires(default='team.manage')]

    def post(self, request):
        refused = _unlicensed()
        if refused:
            return refused
        org = request.user.organisation
        fields, error = _validated(request, org)
        if error:
            return error
        try:
            with transaction.atomic():
                role = CustomRole.objects.create(organisation=org, **fields)
        except IntegrityError:
            return Response({'name': 'A role with this name exists.'}, status=status.HTTP_400_BAD_REQUEST)
        log_action(request, 'ROLE_CREATE', {'role': role.name, 'permissions': role.permissions})
        return Response(serialize_role(role, 0), status=status.HTTP_201_CREATED)


class RoleDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(default='team.manage')]

    def _role(self, request, pk):
        return CustomRole.objects.filter(pk=pk, organisation=request.user.organisation).first()

    def put(self, request, pk):
        role = self._role(request, pk)
        if role is None:
            return Response({'error': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)
        refused = _unlicensed()
        if refused:
            return refused
        # Editing changes what every holder can do: the editor must hold
        # what the role grants today, as well as what it will grant.
        if not can_grant(request.user, role.permissions):
            return Response({'error': 'You can only change roles whose permissions you hold.'},
                            status=status.HTTP_403_FORBIDDEN)
        fields, error = _validated(request, role.organisation, partial=True, current=role)
        if error:
            return error
        before = sorted(role.permissions or [])
        for k, v in fields.items():
            setattr(role, k, v)
        try:
            with transaction.atomic():
                role.save()
        except IntegrityError:
            return Response({'name': 'A role with this name exists.'}, status=status.HTTP_400_BAD_REQUEST)
        log_action(request, 'ROLE_UPDATE', {'role': role.name, 'before': before, 'permissions': role.permissions})
        return Response(serialize_role(role, role.members.count()))

    patch = put

    def delete(self, request, pk):
        role = self._role(request, pk)
        if role is None:
            return Response({'error': 'Role not found'}, status=status.HTTP_404_NOT_FOUND)
        if not can_grant(request.user, role.permissions):
            return Response({'error': 'You can only delete roles whose permissions you hold.'},
                            status=status.HTTP_403_FORBIDDEN)
        members = role.members.count()
        if members:
            return Response({'error': f'{members} member(s) have this role. Give them another role first.'},
                            status=status.HTTP_409_CONFLICT)
        if sso_references(role):
            return Response({'error': 'An SSO rule uses this role. Change the rule first.'},
                            status=status.HTTP_409_CONFLICT)
        name = role.name
        role.delete()
        log_action(request, 'ROLE_DELETE', {'role': name})
        return Response(status=status.HTTP_204_NO_CONTENT)


def _validated(request, org, partial=False, current=None):
    """(fields, None) or (None, error response) for a role body."""
    data = request.data
    fields = {}
    if 'name' in data or not partial:
        name = str(data.get('name') or '').strip()
        if not name or len(name) > 50:
            return None, Response({'name': 'A name of 1 to 50 characters is required.'}, status=400)
        if name.lower() in BUILTIN_ROLES or name.lower() in {n.lower() for n in BUILTIN_NAMES.values()}:
            return None, Response({'name': 'That name belongs to a built-in role.'}, status=400)
        if CustomRole.objects.filter(organisation=org, name__iexact=name).exclude(
                pk=getattr(current, 'pk', None)).exists():
            return None, Response({'name': 'A role with this name exists.'}, status=400)
        fields['name'] = name
    if 'description' in data:
        fields['description'] = str(data.get('description') or '').strip()[:255]
    if 'permissions' in data or not partial:
        try:
            perms = normalise_permissions(data.get('permissions') or [])
        except ValueError as e:
            return None, Response({'permissions': str(e)}, status=400)
        if not can_grant(request.user, perms):
            return None, Response({'error': 'You can only grant permissions you hold.'}, status=403)
        fields['permissions'] = perms
    return fields, None
