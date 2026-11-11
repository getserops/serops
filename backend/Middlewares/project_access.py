"""
Per-project access: teams and restricted projects.

A project is open to the whole organisation (``Project.access_mode =
'organisation'``, the default: members' roles apply) or restricted (only
teams given access see it). A team's grant (``ProjectTeamAccess``) gives
its members a role on one project, on top of what their organisation role
allows. Organisation admins always reach every project.

Only the project-scoped permissions below depend on the project; the rest
(settings, integrations, team…) stay organisation-wide.

Views keep ``Requires(...)`` for the request and filter their querysets
with ``scope()``; ``Requires`` lets a project-scoped request through when
any grant holds the permission, so a view that doesn't scope would leak.
``Middlewares/tests/test_project_scope_coverage.py`` walks every route to
catch that.

An organisation with no restricted project and no grant pays nothing:
``scope()`` returns the queryset unchanged.
"""
from django.db.models import Q

PROJECT_SCOPED = {
    'project.read', 'project.write', 'project.delete',
    'batch.read', 'batch.analyze', 'issue.read', 'issue.update',
}

PROJECT_ROLE_PERMISSIONS = {
    'viewer': {'project.read', 'batch.read', 'issue.read'},
    'user': {'project.read', 'batch.read', 'issue.read', 'project.write', 'batch.analyze', 'issue.update'},
    'admin': set(PROJECT_SCOPED),
}


def _is_org_admin(user):
    return getattr(user, 'role', None) == 'admin'


def _org_scoped(user):
    from Middlewares.rbac import role_permissions
    return role_permissions(user) & PROJECT_SCOPED


def uses_access_control(organisation):
    """Whether the organisation restricts a project or grants a team access."""
    if organisation is None:
        return False
    cached = getattr(organisation, '_uses_project_access', None)
    if cached is None:
        from Projects.models import Project, ProjectTeamAccess
        cached = (Project.objects.filter(organisation=organisation, access_mode=Project.ACCESS_RESTRICTED).exists()
                  or ProjectTeamAccess.objects.filter(project__organisation=organisation).exists())
        organisation._uses_project_access = cached
    return cached


def grants(user):
    """{project_id: permissions} from the user's teams (cached per request)."""
    cached = getattr(user, '_project_grants', None)
    if cached is None:
        from Projects.models import ProjectTeamAccess
        cached = {}
        if getattr(user, 'organisation_id', None) and uses_access_control(user.organisation):
            rows = ProjectTeamAccess.objects.filter(
                team__memberships__user=user, project__organisation_id=user.organisation_id,
            ).values_list('project_id', 'role')
            for project_id, role in rows:
                cached.setdefault(project_id, set()).update(PROJECT_ROLE_PERMISSIONS.get(role, ()))
        user._project_grants = cached
    return cached


def holds_through_grant(user, code):
    """Some team grant gives the user ``code`` on some project."""
    return code in PROJECT_SCOPED and any(code in perms for perms in grants(user).values())


def project_permissions(user, project):
    """The project-scoped permissions the user holds on ``project``."""
    if project is None or project.organisation_id != getattr(user, 'organisation_id', None):
        return set()
    if _is_org_admin(user):
        return set(PROJECT_SCOPED)
    perms = set(grants(user).get(project.pk, ()))
    if project.access_mode != 'restricted':
        perms |= _org_scoped(user)
    return perms


def accessible_project_ids(user, code):
    """Ids of the projects where the user holds ``code``, or None for "every
    project of the organisation" (no filter needed)."""
    if code not in PROJECT_SCOPED or _is_org_admin(user):
        return None
    org = getattr(user, 'organisation', None)
    if not uses_access_control(org):
        return None if code in _org_scoped(user) else set()
    from Projects.models import Project
    ids = {pid for pid, perms in grants(user).items() if code in perms}
    if code in _org_scoped(user):
        ids |= set(Project.objects.filter(organisation=org).exclude(
            access_mode=Project.ACCESS_RESTRICTED).values_list('id', flat=True))
    return ids


def scope(queryset, user, code, field='project'):
    """Keep the rows of projects where the user holds ``code``.

    ``field`` is the lookup to the project (``project``,
    ``project_service__project``…), or ``''`` for a Project queryset. Rows
    without a project (organisation-wide batches) stay visible to members
    whose organisation role holds ``code``.
    """
    ids = accessible_project_ids(user, code)
    if ids is None:
        return queryset
    if not field:
        return queryset.filter(pk__in=ids)
    condition = Q(**{f'{field}__in': ids})
    if code in _org_scoped(user):
        condition |= Q(**{f'{field}__isnull': True})
    return queryset.filter(condition)


def can_on_project(user, project, code):
    """True when the user holds ``code`` on this project."""
    from Middlewares.rbac import has_permission
    if code not in PROJECT_SCOPED:
        return has_permission(user, code)
    return code in project_permissions(user, project)


def scope_signature(user, code='batch.read'):
    """A short cache-key part: '' when the user sees every project."""
    ids = accessible_project_ids(user, code)
    if ids is None:
        return ''
    return 'p' + ','.join(str(i) for i in sorted(ids))


def required_code(view, request):
    """The permission the view's Requires declares for this request."""
    from Middlewares.rbac import is_requires
    for permission_class in getattr(view, 'permission_classes', []):
        if is_requires(permission_class):
            return permission_class.permission_for(request.method, getattr(view, 'action', None))
    return None


def org_level(user, code):
    """The organisation role holds ``code`` (not just a team grant): needed
    for actions that don't belong to an existing project, such as creating
    one."""
    from Middlewares.rbac import has_permission
    return has_permission(user, code)


class ProjectScoped:
    """View mixin: ``self.scoped(qs, field)`` filters by the request's permission."""

    def scoped(self, queryset, field='project', code=None):
        return scope(queryset, self.request.user, code or required_code(self, self.request), field)

    def ensure_project(self, project, code='project.write'):
        """Refuse a create/update aimed at a project outside the caller's
        access (same 404 as a missing project)."""
        from rest_framework.exceptions import NotFound
        if project is not None and not can_on_project(self.request.user, project, code):
            raise NotFound('Project not found')


# Used by serializers alongside scope(): limit a writable relation to the
# requester's rows.
from Utils.scoped_relations import limit_relations  # noqa: E402,F401


def scope_request(view, request, queryset, read_code, write_codes=(), field='project'):
    """scope() by the request's own permission when it writes this resource
    (e.g. issue.update to resolve), else by ``read_code``."""
    code = required_code(view, request)
    return scope(queryset, request.user, code if code in write_codes else read_code, field)


def can_grant_project_role(actor, project, role):
    """No escalation through teams: the actor holds, on this project, every
    permission the project role gives."""
    return PROJECT_ROLE_PERMISSIONS.get(role, set()) <= project_permissions(actor, project)


def can_manage_team(actor, team):
    """The actor holds every permission the team's grants give, so changing
    its members (or deleting it) hands out nothing they lack."""
    return all(can_grant_project_role(actor, access.project, access.role)
               for access in team.project_access.select_related('project'))


class OrgRoleOnly:
    """DRF permission: the organisation role must hold the route's
    permission; a team grant on some project is not enough. For legacy
    routes that act on the whole organisation's repositories or onboarding
    and filter by no project: a viewer whose team is admin of one project
    could rewrite or delete any of them (review 2026-11-05)."""

    def has_permission(self, request, view):
        code = required_code(view, request)
        return code is None or org_level(request.user, code)

    def has_object_permission(self, request, view, obj):
        return True
