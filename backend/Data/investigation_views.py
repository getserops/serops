"""Investigations: an analysis a user asks for, for one scope and window.

POST /api/data/investigations/            start one (role user or above)
GET  /api/data/investigations/            this organisation's runs, newest first
GET  /api/data/investigations/options/    projects, environments, deployments, services
GET  /api/data/investigations/<id>/       one run, with its progress
"""
from Middlewares.rbac import Requires
import logging
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


from .models import AIAnalyzedBatch, Investigation

logger = logging.getLogger(__name__)

MAX_ACTIVE_PER_ORG = 2
MAX_PER_HOUR_PER_ORG = 10
MAX_SERVICES = 20
# A log provider rarely keeps more; an older window would only come back empty.
MAX_LOOKBACK_DAYS = 30
DEDUP_SECONDS = 120
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _error(code, message, http_status=status.HTTP_400_BAD_REQUEST):
    return Response({'error': code, 'message': message}, status=http_status)


def _named(obj):
    return {'id': obj.id, 'name': obj.name} if obj is not None else None


def serialize(inv, batch=None):
    if batch is None:
        batch = getattr(inv, '_batch', None) or AIAnalyzedBatch.objects.filter(
            investigation=inv).only('batch_id', 'issue_count').first()
    user = inv.requested_by
    return {
        'id': inv.id,
        'status': inv.status,
        'status_label': inv.get_status_display(),
        'project': _named(inv.project),
        'environment': _named(inv.environment),
        'deployment': _named(inv.deployment),
        'services': inv.services,
        'window_start': inv.window_start.isoformat(),
        'window_end': inv.window_end.isoformat(),
        'hint': inv.hint,
        'notify_routing': inv.notify_routing,
        'counts': inv.counts,
        'error_code': inv.error_code,
        'error': inv.error,
        'requested_by': ({'id': user.id, 'name': user.get_full_name() or user.email}
                         if user is not None else None),
        'created_at': inv.created_at.isoformat(),
        'started_at': inv.started_at.isoformat() if inv.started_at else None,
        'finished_at': inv.finished_at.isoformat() if inv.finished_at else None,
        'batch_id': batch.batch_id if batch else None,
        'issue_count': batch.issue_count if batch and inv.status == Investigation.STATUS_DONE else None,
    }


def _parse_when(value, field):
    when = parse_datetime(value) if isinstance(value, str) else None
    if when is None:
        raise ValueError(f'{field} must be an ISO-8601 date and time.')
    if timezone.is_naive(when):
        raise ValueError(f'{field} must include a time zone (for example 2026-10-14T12:00:00Z).')
    return when


def _validate(data, org):
    """Return (fields, None) or (None, error Response)."""
    from Projects.models import Project, ProjectDeployment, ProjectEnvironment, ProjectService

    try:
        project = Project.objects.get(pk=int(data.get('project_id')), organisation=org)
    except (TypeError, ValueError, Project.DoesNotExist):
        return None, _error('invalid_project', 'Choose a project in your organisation.')

    environment = deployment = None
    if data.get('environment_id') not in (None, ''):
        try:
            environment = ProjectEnvironment.objects.get(pk=int(data['environment_id']), project=project)
        except (TypeError, ValueError, ProjectEnvironment.DoesNotExist):
            return None, _error('invalid_environment', 'That environment is not part of the project.')
    if data.get('deployment_id') not in (None, ''):
        try:
            deployment = ProjectDeployment.objects.get(pk=int(data['deployment_id']), project=project)
        except (TypeError, ValueError, ProjectDeployment.DoesNotExist):
            return None, _error('invalid_deployment', 'That deployment is not part of the project.')
        if environment is None:
            environment = deployment.environment
        elif deployment.environment_id not in (None, environment.id):
            return None, _error('invalid_deployment', 'That deployment runs in another environment.')

    services = data.get('services') or []
    if not isinstance(services, list) or len(services) > MAX_SERVICES or \
            not all(isinstance(s, str) and s.strip() for s in services):
        return None, _error('invalid_services', f'Services must be a list of up to {MAX_SERVICES} names.')
    known = {name.lower(): name for name in
             ProjectService.objects.filter(project=project).values_list('name', flat=True) if name}
    unknown = [s for s in services if s.strip().lower() not in known]
    if unknown:
        return None, _error('invalid_services', f"Not services of this project: {', '.join(unknown[:5])}.")
    services = sorted({known[s.strip().lower()] for s in services})

    try:
        start = _parse_when(data.get('window_start'), 'window_start')
        end = _parse_when(data.get('window_end'), 'window_end')
    except ValueError as exc:
        return None, _error('invalid_window', str(exc))
    now = timezone.now()
    if end > now + timedelta(minutes=1):
        return None, _error('invalid_window', 'The window cannot end in the future.')
    end = min(end, now)
    length = end - start
    if length < timedelta(minutes=Investigation.MIN_WINDOW_MINUTES):
        return None, _error('invalid_window',
                            f'The window must be at least {Investigation.MIN_WINDOW_MINUTES} minutes long.')
    if length > timedelta(hours=Investigation.MAX_WINDOW_HOURS):
        return None, _error('invalid_window',
                            f'The window can be at most {Investigation.MAX_WINDOW_HOURS} hours long.')
    if start < now - timedelta(days=MAX_LOOKBACK_DAYS):
        return None, _error('invalid_window', f'The window must start within the last {MAX_LOOKBACK_DAYS} days.')

    hint = data.get('hint') or ''
    if not isinstance(hint, str):
        return None, _error('invalid_hint', 'The description must be text.')
    hint = _CONTROL_CHARS.sub('', hint).strip()
    if len(hint) > Investigation.HINT_MAX_LENGTH:
        return None, _error('invalid_hint',
                            f'Keep the description under {Investigation.HINT_MAX_LENGTH} characters.')

    notify_routing = data.get('notify_routing', False)
    if not isinstance(notify_routing, bool):
        return None, _error('invalid_notify_routing', 'notify_routing must be true or false.')

    return {
        'project': project, 'environment': environment, 'deployment': deployment,
        'services': services, 'window_start': start, 'window_end': end,
        'hint': hint, 'notify_routing': notify_routing,
    }, None


def _last_deploy_at(org, project):
    """When the project's newest pipeline ran, for the "since the last deploy" preset."""
    from django.db.models import Q
    from providers.models import Pipeline
    query = Q()
    for service in project.services.all():
        binding = getattr(service, 'scm_binding', None)
        if binding is not None and binding.repository_id:
            query |= Q(external_project_id=binding.repository_id)
        if service.gitlab_project_id:
            query |= Q(project_id=service.gitlab_project_id)
    if not query:
        return None
    latest = (Pipeline.objects.filter(query, organisation=org)
              .order_by('-created_at').values_list('created_at', flat=True).first())
    return latest.isoformat() if latest else None


class InvestigationListView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='batch.read', POST='batch.analyze')]

    def get(self, request):
        org = request.user.organisation
        if org is None:
            return Response({'results': [], 'count': 0})
        qs = (Investigation.objects.filter(organisation=org)
              .select_related('project', 'environment', 'deployment', 'requested_by'))
        project_id = request.query_params.get('project_id')
        if project_id:
            if not project_id.isdigit():
                return _error('invalid_project', 'project_id must be a number.')
            qs = qs.filter(project_id=int(project_id))
        try:
            limit = max(1, min(50, int(request.query_params.get('limit', 20))))
            offset = max(0, int(request.query_params.get('offset', 0)))
        except ValueError:
            return _error('invalid_page', 'limit and offset must be numbers.')
        page = list(qs[offset:offset + limit])
        batches = {b.investigation_id: b for b in AIAnalyzedBatch.objects.filter(
            investigation__in=page).only('batch_id', 'issue_count', 'investigation_id')}
        for inv in page:
            inv.settle()
        return Response({
            'count': qs.count(),
            'results': [serialize(inv, batches.get(inv.id)) for inv in page],
        })

    def post(self, request):
        org = request.user.organisation
        if org is None:
            return _error('no_organisation', 'Your account does not belong to an organisation.',
                          status.HTTP_403_FORBIDDEN)
        fields, err = _validate(request.data, org)
        if err is not None:
            return err

        now = timezone.now()
        recent = Investigation.objects.filter(organisation=org)
        for inv in recent.filter(status__in=Investigation.ACTIVE_STATUSES):
            inv.settle()

        # The same request moments ago (a double click, a retry): return it.
        duplicate = recent.filter(
            requested_by=request.user, project=fields['project'], environment=fields['environment'],
            deployment=fields['deployment'], services=fields['services'], hint=fields['hint'],
            created_at__gte=now - timedelta(seconds=DEDUP_SECONDS),
            window_start__range=(fields['window_start'] - timedelta(minutes=1),
                                 fields['window_start'] + timedelta(minutes=1)),
            window_end__range=(fields['window_end'] - timedelta(minutes=1),
                               fields['window_end'] + timedelta(minutes=1)),
        ).exclude(status=Investigation.STATUS_FAILED).first()
        if duplicate is not None:
            return Response(serialize(duplicate), status=status.HTTP_200_OK)

        if recent.filter(status__in=Investigation.ACTIVE_STATUSES).count() >= MAX_ACTIVE_PER_ORG:
            return _error('too_many_running',
                          f'{MAX_ACTIVE_PER_ORG} investigations are already running. Wait for one to finish.',
                          status.HTTP_429_TOO_MANY_REQUESTS)
        if recent.filter(created_at__gte=now - timedelta(hours=1)).count() >= MAX_PER_HOUR_PER_ORG:
            return _error('rate_limited',
                          f'Your organisation can start {MAX_PER_HOUR_PER_ORG} investigations an hour. '
                          'Try again later.', status.HTTP_429_TOO_MANY_REQUESTS)

        from ai_model.budget import BudgetTracker
        budget = BudgetTracker.check_budget(org)
        if not budget.ok:
            return _error('over_budget',
                          'The monthly AI budget is used up. Raise it in Settings → AI, '
                          'or wait for the next month.', status.HTTP_409_CONFLICT)

        inv = Investigation.objects.create(organisation=org, requested_by=request.user, **fields)

        from .audit import log_action
        log_action(request, 'INVESTIGATION_RUN', details={
            'investigation_id': inv.id, 'project_id': inv.project_id,
            'window_start': inv.window_start.isoformat(), 'window_end': inv.window_end.isoformat(),
        })

        from .tasks import run_investigation
        transaction.on_commit(lambda: run_investigation.delay(inv.id))
        return Response(serialize(inv), status=status.HTTP_202_ACCEPTED)


class InvestigationDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='batch.read')]

    def get(self, request, pk):
        inv = (Investigation.objects
               .select_related('project', 'environment', 'deployment', 'requested_by')
               .filter(pk=pk, organisation=request.user.organisation).first())
        if inv is None or request.user.organisation is None:
            return _error('not_found', 'No such investigation.', status.HTTP_404_NOT_FOUND)
        inv.settle()
        return Response(serialize(inv))


class InvestigationOptionsView(APIView):
    """Everything the form needs, in one call, scoped to the organisation."""
    permission_classes = [IsAuthenticated, Requires(GET='project.read')]

    def get(self, request):
        from Projects.models import Project
        org = request.user.organisation
        if org is None:
            return Response({'projects': []})
        projects = (Project.objects.filter(organisation=org).order_by('name')
                    .prefetch_related('environments', 'deployments', 'services__scm_binding'))
        return Response({
            'limits': {
                'min_window_minutes': Investigation.MIN_WINDOW_MINUTES,
                'max_window_hours': Investigation.MAX_WINDOW_HOURS,
                'hint_max_length': Investigation.HINT_MAX_LENGTH,
                'max_lookback_days': MAX_LOOKBACK_DAYS,
            },
            'projects': [{
                'id': p.id,
                'name': p.name,
                'environments': [{'id': e.id, 'name': e.name, 'display_name': e.display_name or e.name}
                                 for e in p.environments.all() if e.is_active],
                'deployments': [{'id': d.id, 'name': d.name, 'environment_id': d.environment_id}
                                for d in p.deployments.all() if d.is_active],
                'services': sorted(s.name for s in p.services.all() if s.name),
                'last_deploy_at': _last_deploy_at(org, p),
            } for p in projects],
        })
