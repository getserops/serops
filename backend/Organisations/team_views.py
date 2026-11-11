"""
Teams: groups of members that restricted projects are opened to.

A member edits a team (or its members) only if they hold every permission
the team's project grants give: adding yourself to a team that is admin of
a project must not be a way to become its admin.
"""
from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.project_access import can_manage_team
from Middlewares.rbac import Requires
from Users.models import User

from .models import Team, TeamMembership


def serialize_team(team, viewer):
    """A team, with only the projects the viewer can see."""
    from Middlewares.project_access import accessible_project_ids
    visible = accessible_project_ids(viewer, 'project.read')
    return {
        'id': team.pk,
        'name': team.name,
        'description': team.description,
        'members': [{'id': m.user_id, 'email': m.user.email,
                     'name': f'{m.user.first_name} {m.user.last_name}'.strip(), 'source': m.source}
                    for m in team.memberships.select_related('user').order_by('user__email')],
        'projects': [{'id': a.project_id, 'name': a.project.name, 'role': a.role}
                     for a in team.project_access.select_related('project').order_by('project__name')
                     if visible is None or a.project_id in visible],
    }


def _member_ids(request, org):
    """Validated member ids from the body (all of the caller's organisation)."""
    raw = request.data.get('member_ids')
    if raw is None:
        return None, None
    if not isinstance(raw, list) or not all(isinstance(i, int) for i in raw):
        return None, Response({'member_ids': 'A list of user ids is required.'}, status=400)
    ids = set(raw)
    if User.objects.filter(pk__in=ids, organisation=org).count() != len(ids):
        return None, Response({'member_ids': 'Unknown member.'}, status=400)
    return ids, None


def _set_members(team, ids):
    current = {m.user_id: m for m in team.memberships.all()}
    TeamMembership.objects.filter(team=team).exclude(user_id__in=ids).delete()
    TeamMembership.objects.bulk_create(
        [TeamMembership(team=team, user_id=i, source='manual') for i in ids if i not in current])


def _name(request, org, current=None):
    name = str(request.data.get('name') or '').strip()
    if not name or len(name) > 80:
        return None, Response({'name': 'A name of 1 to 80 characters is required.'}, status=400)
    if Team.objects.filter(organisation=org, name__iexact=name).exclude(pk=getattr(current, 'pk', None)).exists():
        return None, Response({'name': 'A team with this name exists.'}, status=400)
    return name, None


class TeamListView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='org.read', POST='team.manage')]

    def get(self, request):
        teams = Team.objects.filter(organisation=request.user.organisation)
        return Response({'teams': [serialize_team(t, request.user) for t in teams]})

    def post(self, request):
        org = request.user.organisation
        name, error = _name(request, org)
        if error:
            return error
        ids, error = _member_ids(request, org)
        if error:
            return error
        try:
            with transaction.atomic():
                team = Team.objects.create(organisation=org, name=name,
                                           description=str(request.data.get('description') or '')[:255])
                _set_members(team, ids or set())
        except IntegrityError:
            return Response({'name': 'A team with this name exists.'}, status=400)
        log_action(request, 'TEAM_CREATE', {'team': team.name, 'members': sorted(ids or [])})
        return Response(serialize_team(team, request.user), status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='org.read', default='team.manage')]

    def _team(self, request, pk):
        return Team.objects.filter(pk=pk, organisation=request.user.organisation).first()

    def get(self, request, pk):
        team = self._team(request, pk)
        if team is None:
            return Response({'error': 'Team not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_team(team, request.user))

    def put(self, request, pk):
        team = self._team(request, pk)
        if team is None:
            return Response({'error': 'Team not found'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_team(request.user, team):
            return Response({'error': "You can only change teams whose project access you hold."},
                            status=status.HTTP_403_FORBIDDEN)
        if 'name' in request.data:
            name, error = _name(request, team.organisation, current=team)
            if error:
                return error
            team.name = name
        if 'description' in request.data:
            team.description = str(request.data.get('description') or '')[:255]
        ids, error = _member_ids(request, team.organisation)
        if error:
            return error
        with transaction.atomic():
            team.save()
            if ids is not None:
                _set_members(team, ids)
        log_action(request, 'TEAM_UPDATE', {'team': team.name, 'members': sorted(ids) if ids is not None else None})
        return Response(serialize_team(team, request.user))

    patch = put

    def delete(self, request, pk):
        team = self._team(request, pk)
        if team is None:
            return Response({'error': 'Team not found'}, status=status.HTTP_404_NOT_FOUND)
        if not can_manage_team(request.user, team):
            return Response({'error': "You can only delete teams whose project access you hold."},
                            status=status.HTTP_403_FORBIDDEN)
        from Users.models import SecuritySettings
        sec = SecuritySettings.objects.filter(organisation=team.organisation).first()
        if sec and any(r.get('team_id') == team.pk for r in sec.sso_team_mappings or []):
            return Response({'error': 'An SSO rule uses this team. Change the rule first.'},
                            status=status.HTTP_409_CONFLICT)
        name = team.name
        team.delete()
        log_action(request, 'TEAM_DELETE', {'team': name})
        return Response(status=status.HTTP_204_NO_CONTENT)
