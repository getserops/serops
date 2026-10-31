"""
"Check my data": what the scheduled analysis of a project environment
would find in the log store right now, step by step, and why it finds
nothing when it finds nothing.

Each step is the scheduled query with one more filter, sent to the
organisation's own log store, so the counts are what the store really
returns, not an estimate:

    found        every log in the places the project reads from
    project      ... tagged with the project
    environment  ... and with the environment (or one of its spellings)
    level        ... errors and warnings
    services     ... from the services the project lists: what gets analysed

Alongside the counts it reports the project, environment and service
VALUES seen in the logs (identifiers such as ``checkout`` or ``prod``,
never log messages), so the person sees what their logs say instead of
guessing, and fixes that are one click away: list a service seen in the
logs, or accept the environment value the logs carry.
"""
import logging
from collections import Counter
from datetime import timedelta

from django.utils import timezone

from integrations.field_aliases import (
    ENVIRONMENT_ALIASES,
    PROJECT_NAME_ALIASES,
    environment_values,
    first_present,
    first_present_with_key,
    lookup,
)
from integrations.ingestion import is_log_matching_environment
from integrations.schemas import LogQuery

from .log_filters import (
    SEVERITIES,
    is_important_log,
    log_service,
    project_log_locations,
    registered_service_names,
    system_indices,
)

logger = logging.getLogger(__name__)

# Fields teams group services by when they have no project field: offered as
# project log rules (Project.log_rules) for the logs that carry no project.
GROUPING_FIELDS = [
    'service.namespace',                        # OpenTelemetry
    'resource.attributes.service.namespace',    # OTel Collector elasticsearch exporter (otel mode)
    'service_namespace',                        # Loki OTLP ingestion label
    'kubernetes.namespace',                     # Filebeat / Elastic Agent
    'kubernetes.namespace_name',                # Fluent Bit
    'k8s.namespace.name',                       # OpenTelemetry Kubernetes attributes
    'namespace',                                # Promtail / Loki label
    'kubernetes.labels.app_kubernetes_io/part-of',  # Fluent Bit, Replace_Dots
    'kubernetes.labels.app.kubernetes.io/part-of',
    'app.kubernetes.io/part-of',
    'kubernetes.labels.team',
    'team',
]

# Logs read per step. Counts at the cap are shown as "1000+".
SAMPLE_SIZE = 1000
DEFAULT_MINUTES = 60
MAX_MINUTES = 24 * 60
TOP_VALUES = 8


def _top_values(entries, aliases):
    """The most common values of a field across the sample, with the field
    name that carried each (``service.name``, ``kubernetes.labels.app``...)."""
    counts, fields = Counter(), {}
    for entry in entries:
        key, value = first_present_with_key(getattr(entry, 'labels', None) or {}, aliases)
        if key is None:
            continue
        value = str(value)
        counts[value] += 1
        fields.setdefault(value, key)
    return [{'value': v, 'count': n, 'field': fields[v]} for v, n in counts.most_common(TOP_VALUES)]


def _groupings(entries, project_name, rules):
    """How the logs that carry no project (and match no rule) are grouped:
    [{field, value, count, matches_name}], values equal to the project name first."""
    counts = Counter()
    for entry in entries:
        labels = getattr(entry, 'labels', None) or {}
        if first_present(labels, PROJECT_NAME_ALIASES, default=None):
            continue
        if any(str(lookup(labels, f)) == v for f, v in rules):
            continue
        for field in GROUPING_FIELDS:
            value = lookup(labels, field)
            if value not in (None, '') and not isinstance(value, (dict, list)):
                counts[(field, str(value))] += 1
    rows = [{'field': f, 'value': v, 'count': n, 'matches_name': v.lower() == project_name.lower()}
            for (f, v), n in counts.items()]
    rows.sort(key=lambda r: (not r['matches_name'], -r['count']))
    return rows[:TOP_VALUES]


def _service_values(entries, registered):
    counts = Counter(log_service(e) for e in entries if log_service(e))
    return [{'value': v, 'count': n, 'registered': v in registered}
            for v, n in counts.most_common(TOP_VALUES)]


def check_project_data(project, environment=None, minutes=DEFAULT_MINUTES):
    from integrations.registry import IntegrationRegistry

    minutes = max(1, min(int(minutes or DEFAULT_MINUTES), MAX_MINUTES))
    end = timezone.now()
    start = end - timedelta(minutes=minutes)
    report = {
        'project': project.name,
        'environment': environment.name if environment else None,
        'environment_values': (environment_values(environment.name, environment.log_labels())
                               if environment else []),
        'window_minutes': minutes,
        'sample_size': SAMPLE_SIZE,
        'locations': [],
        'stages': [],
        'seen': {'project': [], 'environment': [], 'service': [], 'level': [], 'groupings': []},
        'project_rules': [{'field': f, 'value': v} for f, v in project.log_rules_clean()],
        'diagnosis': None,
        'fixes': [],
    }

    try:
        provider = IntegrationRegistry.get_log_provider_for_org(
            project.organisation, cluster=getattr(project, 'cluster', None))
    except Exception as e:
        logger.info('Check my data: no log provider for %s: %s', project, e)
        provider = None
    if provider is None:
        report['diagnosis'] = _diagnosis('no_log_provider')
        return report

    locations = project_log_locations(project, provider)
    report['locations'] = locations
    if not locations:
        report['diagnosis'] = _diagnosis('no_log_location')
        return report
    index = ','.join(locations + system_indices(provider))

    registered = registered_service_names(project)
    env_labels = environment.log_labels() if environment else []

    def run(key, **filters):
        if filters.get('project'):
            filters['project_rules'] = project.log_rules_clean() or None
        query = LogQuery(time_range=(start, end), max_results=SAMPLE_SIZE, **filters)
        try:
            entries = list(provider.search(index, query))
        except Exception as e:
            report['stages'].append({'key': key, 'count': None, 'error': str(e)[:500]})
            return None
        report['stages'].append({'key': key, 'count': len(entries), 'capped': len(entries) >= SAMPLE_SIZE})
        return entries

    def stop(code, **extra):
        report['diagnosis'] = _diagnosis(code, **extra)
        return report

    found = run('found')
    if found is None:
        return stop('search_failed', error=report['stages'][-1]['error'])
    report['seen']['project'] = _top_values(found, PROJECT_NAME_ALIASES)
    report['seen']['groupings'] = _groupings(found, project.name, project.log_rules_clean())
    if len(project.log_rules_clean()) < project.MAX_LOG_RULES:
        report['fixes'] += [{'action': 'add_project_rule', 'field': g['field'], 'value': g['value']}
                            for g in report['seen']['groupings'] if g['matches_name']][:2]
    if not found:
        return stop('no_logs', minutes=minutes)

    scoped = run('project', project=project.name)
    if scoped is None:
        return stop('search_failed', error=report['stages'][-1]['error'])
    report['seen']['environment'] = _top_values(scoped or found, ENVIRONMENT_ALIASES)
    if not scoped:
        report['seen']['service'] = _service_values(found, registered)
        return stop('project_not_tagged', project=project.name,
                    same_but_case=[v['value'] for v in report['seen']['project']
                                   if v['value'].lower() == project.name.lower()])

    if environment:
        in_env = run('environment', project=project.name, environment=environment.name,
                     environment_labels=env_labels or None)
        if in_env is None:
            return stop('search_failed', error=report['stages'][-1]['error'])
    else:
        in_env = scoped
    report['seen']['service'] = _service_values(in_env or scoped, registered)
    report['seen']['level'] = [{'value': v, 'count': n} for v, n in
                               Counter((e.level or 'INFO').upper() for e in (in_env or scoped)).most_common()]
    if environment:
        # Values the project's logs carry that belong to none of its
        # environments ("live" next to "prod"): offered even when some logs
        # match, or the logs one team tags differently are silently left out.
        # A value another environment claims ("staging") is never offered.
        from Projects.models import ProjectEnvironment
        claimed = {v.lower() for v in report['environment_values']}
        for other in ProjectEnvironment.objects.filter(project=project).exclude(pk=environment.pk):
            claimed |= {v.lower() for v in environment_values(other.name, other.log_labels())}
        stray = [v['value'] for v in report['seen']['environment'] if v['value'].lower() not in claimed]
        report['fixes'] += [{'action': 'use_environment_label', 'environment': environment.id, 'value': v}
                            for v in stray[:3]]
    if not in_env:
        return stop('environment_not_tagged', environment=environment.name)

    errors = run('level', project=project.name, severity=SEVERITIES,
                 environment=environment.name if environment else None,
                 environment_labels=env_labels or None)
    if errors is None:
        return stop('search_failed', error=report['stages'][-1]['error'])
    errors = [e for e in errors if is_important_log(e)]
    report['stages'][-1].update(count=len(errors))
    if not errors:
        return stop('no_errors', minutes=minutes)

    analysed = [e for e in errors if log_service(e) in registered
                and is_log_matching_environment(e, environment.name if environment else None, env_labels)]
    report['stages'].append({'key': 'services', 'count': len(analysed),
                             'capped': report['stages'][-1].get('capped', False)})
    unlisted = sorted({log_service(e) for e in errors if log_service(e) and log_service(e) not in registered})
    if unlisted:
        report['fixes'].append({'action': 'register_services', 'names': unlisted[:20]})
    if not analysed:
        return stop('no_services' if not registered else 'unregistered_services', services=unlisted)
    return stop('ok', count=len(analysed))


# Words for the person, keyed by the step that left nothing.
_MESSAGES = {
    'no_log_provider': 'No active log integration. Connect one in Settings → Observability.',
    'no_log_location': ('SerOps found no index, log group or stream with logs for this project. '
                        'Set where your logs are in the log integration (index pattern or log groups).'),
    'search_failed': 'The log store refused the query: {error}',
    'no_logs': ('The log store has no logs at all in the last {minutes} minutes in the places this '
                'project reads from. Check that your shipper is running and sending to this store.'),
    'project_not_tagged': ('Logs are arriving, but none carry project_name = "{project}". Add that '
                           'field (or label, or tag) to your logs in the shipper; the values your logs '
                           'carry today are listed below.'),
    'environment_not_tagged': ('Logs for this project are arriving, but none carry the environment '
                               '"{environment}" or one of its spellings. Use a value your logs carry, '
                               'or tag the logs with this environment.'),
    'no_errors': ('Logs reach SerOps and are tagged correctly. There were no errors or warnings in the '
                  'last {minutes} minutes, so there was nothing to analyse. That is good news.'),
    'no_services': ('Errors and warnings are arriving, but the project lists no services yet. List '
                    'the services below to analyse them.'),
    'unregistered_services': ('Errors and warnings are arriving, but only from services this project '
                              'does not list. List them to analyse them.'),
    'ok': 'Everything is in place: {count} errors and warnings would be analysed now.',
}


def _diagnosis(code, **extra):
    message = _MESSAGES[code].format(**{k: v for k, v in extra.items() if isinstance(v, (str, int))})
    return {'code': code, 'message': message, **extra}


def apply_fix(project, fix, request=None):
    """Apply one fix offered by :func:`check_project_data`. Returns a short
    summary; raises ``ValueError`` on anything not offered by the check."""
    from Projects.models import ProjectEnvironment, ProjectService

    action = fix.get('action')
    if action == 'register_services':
        names = [str(n).strip() for n in fix.get('names') or [] if str(n).strip()]
        if not names:
            raise ValueError('names is required')
        existing = registered_service_names(project)
        added = []
        for name in names[:20]:
            if name.lower() in existing or len(name) > 255:
                continue
            service = ProjectService.objects.create(project=project, name=name, service_type='application')
            existing.add(name.lower())
            added.append(name)
            if request is not None:
                from .audit import log_service_action
                log_service_action(request, 'SERVICE_CREATE', name, service_id=service.id,
                                   details={'project_id': project.id, 'source': 'check_my_data'})
        return {'added': added}

    if action == 'use_environment_label':
        value = str(fix.get('value') or '').strip()
        if not value or ',' in value or len(value) > 100:
            raise ValueError('value must be one environment value')
        env = ProjectEnvironment.objects.filter(project=project, pk=fix.get('environment')).first()
        if env is None:
            raise ValueError('environment not found')
        labels = env.log_labels()
        if value.lower() not in {v.lower() for v in labels}:
            joined = ','.join(labels + [value])
            if len(joined) > 100:
                raise ValueError('too many environment values')
            env.log_label_value = joined
            env.save(update_fields=['log_label_value', 'updated_at'])
        return {'environment': env.id, 'log_label_value': env.log_label_value}

    if action in ('add_project_rule', 'remove_project_rule'):
        field, value = project.clean_log_rule(fix.get('field'), fix.get('value'))
        rules = [{'field': f, 'value': v} for f, v in project.log_rules_clean()]
        rule = {'field': field, 'value': value}
        if action == 'add_project_rule' and rule not in rules:
            if len(rules) >= project.MAX_LOG_RULES:
                raise ValueError(f'a project has at most {project.MAX_LOG_RULES} log rules')
            rules.append(rule)
        elif action == 'remove_project_rule':
            rules = [r for r in rules if r != rule]
        project.log_rules = rules
        project.save(update_fields=['log_rules', 'updated_at'])
        if request is not None:
            from .audit import log_action
            log_action(request, 'SETTINGS_CHANGE', details={'type': 'project_log_rules', 'project_id': project.id, 'log_rules': rules,
                                                          'source': 'check_my_data'})
        return {'project_rules': rules}

    raise ValueError('unknown action')
