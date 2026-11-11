"""
Per-project access (Enterprise, feature ``project_access``).

Enforcement is Community (``Middlewares/project_access.py``): restricted
projects stay restricted whatever the license. Managing them is here.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Middlewares.project_access import (PROJECT_ROLE_PERMISSIONS, ProjectScoped, can_grant_project_role,
                                        project_permissions, scope)
from Middlewares.rbac import Requires
from Projects.models import Project, ProjectTeamAccess
from Utils import edition

FEATURE = 'project_access'


def _widens_restriction(project, mode, grants):
    """True when the change restricts the project, or adds or raises a grant.

    ``grants`` is the requested {team_id: role}, or None when unchanged.
    """
    if mode == 'restricted' and project.access_mode != 'restricted':
        return True
    if grants is None:
        return False
    order = list(PROJECT_ROLE_PERMISSIONS)  # viewer, user, admin
    current = dict(ProjectTeamAccess.objects.filter(project=project).values_list('team_id', 'role'))
    return any(team_id not in current or order.index(role) > order.index(current[team_id])
               for team_id, role in grants.items())


class ProjectAccessView(ProjectScoped, APIView):
    """Who sees a project: everyone in the organisation, or only the teams
    given access (with a role on this project). Changing it needs team.manage
    and the admin permissions on this project (organisation admins have
    them on every project).

    Restricting a project or adding or changing a team grant needs the
    license; opening a project to the organisation and removing grants
    never does."""
    permission_classes = [IsAuthenticated, Requires(GET='project.read', PUT='team.manage')]

    def _project(self, request, pk, code):
        return scope(Project.objects.filter(organisation=request.user.organisation), request.user, code,
                     field='').filter(pk=pk).first()

    def _body(self, project):
        return {
            'project_id': project.pk,
            'access_mode': project.access_mode,
            'grants': [{'team_id': a.team_id, 'team_name': a.team.name, 'role': a.role}
                       for a in ProjectTeamAccess.objects.filter(project=project).select_related('team')
                       .order_by('team__name')],
        }

    def get(self, request, pk):
        project = self._project(request, pk, 'project.read')
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(self._body(project))

    def put(self, request, pk):
        from django.db import transaction
        from Organisations.models import Team
        from Data.audit import log_action
        project = self._project(request, pk, 'project.read')
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        if not PROJECT_ROLE_PERMISSIONS['admin'] <= project_permissions(request.user, project):
            return Response({"error": "Only admins of this project can change who sees it."},
                            status=status.HTTP_403_FORBIDDEN)
        mode = request.data.get('access_mode', project.access_mode)
        if mode not in dict(Project.ACCESS_MODES):
            return Response({"access_mode": "organisation or restricted"}, status=status.HTTP_400_BAD_REQUEST)
        grants = request.data.get('grants')
        if grants is not None:
            if not isinstance(grants, list):
                return Response({"grants": "A list of {team_id, role}."}, status=status.HTTP_400_BAD_REQUEST)
            parsed = {}
            for g in grants:
                team_id = g.get('team_id') if isinstance(g, dict) else None
                role = g.get('role') if isinstance(g, dict) else None
                if role not in PROJECT_ROLE_PERMISSIONS or not isinstance(team_id, int):
                    return Response({"grants": "Each grant needs a team_id and a role (viewer, user, admin)."},
                                    status=status.HTTP_400_BAD_REQUEST)
                parsed[team_id] = role
            teams = Team.objects.filter(pk__in=parsed, organisation=request.user.organisation)
            if teams.count() != len(parsed):
                return Response({"grants": "Unknown team."}, status=status.HTTP_400_BAD_REQUEST)
            if not all(can_grant_project_role(request.user, project, r) for r in parsed.values()):
                return Response({"error": "You can only grant roles whose permissions you hold."},
                                status=status.HTTP_403_FORBIDDEN)
        if not edition.has_feature(FEATURE) and _widens_restriction(project, mode, parsed if grants is not None else None):
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        before = self._body(project)
        with transaction.atomic():
            project.access_mode = mode
            project.save(update_fields=['access_mode', 'updated_at'])
            if grants is not None:
                ProjectTeamAccess.objects.filter(project=project).exclude(team_id__in=parsed).delete()
                for team_id, role in parsed.items():
                    ProjectTeamAccess.objects.update_or_create(project=project, team_id=team_id, defaults={'role': role})
        after = self._body(project)
        log_action(request, 'PROJECT_ACCESS_CHANGE', {
            'project': project.name, 'access_mode': after['access_mode'],
            'grants': [{'team': g['team_name'], 'role': g['role']} for g in after['grants']],
            'before': {'access_mode': before['access_mode'],
                       'grants': [{'team': g['team_name'], 'role': g['role']} for g in before['grants']]}})
        return Response(after)
