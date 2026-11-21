"""
Metric Processing Module — extracted from Data/tasks.py (Phase 4).

Contains all metric computation logic:
- Provider-based metric fetching
- Memory usage calculation
- CPU usage calculation
- AI-friendly metric preprocessing (anomaly detection, trends)
- JSON sanitization
"""

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from integrations.base import MetricQueryError, note_partial

# NOTE: deliberately NOT django.utils.timezone. This module only ever wanted
# `timezone.utc`, and Django removed that alias in 5.0 — every reference to it
# raised AttributeError inside a broad `except`, so the sustained-anomaly
# branch could never complete on Django 5 regardless of its input.

logger = logging.getLogger(__name__)

# Kubernetes CPU: percent of one core, summed over a service's replicas.
CPU_UNIT_CORE_PERCENT = 'core_percent'


def fetch_metrics_with_provider(start_time, end_time, project_obj=None, project_name_str=None, environment_str=None):
    """
    Fetch metrics using the configured MetricProvider for the organisation.
    Handles label filtering for org/project/environment implicitly via the provider adapter.
    """
    from integrations.registry import IntegrationRegistry
    
    # Defaults
    provider = None
    labels = {}
    
    # Try to determine provider from project's organization.
    # Item #17 / Q1.4: pass cluster so per-cluster Prometheus /
    # Mimir / etc. gets queried when the project is assigned to
    # a specific cluster.
    if project_obj and hasattr(project_obj, 'organisation') and project_obj.organisation:
        try:
            provider = IntegrationRegistry.get_metric_provider_for_org(
                project_obj.organisation,
                cluster=getattr(project_obj, 'cluster', None),
            )
            if project_obj.organisation.name:
                labels['organisation_name'] = project_obj.organisation.name
        except Exception as e:
            logger.warning(f"Error getting provider for org: {e}")
            
    if not provider:
        # `metrics` is not bound until further down, so this used to raise
        # UnboundLocalError — for every org that has logs but no metric
        # provider, which onboarding explicitly allows (one observability
        # provider is required, and Loki/ES alone satisfy it). Returning a
        # bare {} is also wrong: callers index metrics['memory_total']
        # directly, so the shape has to match the error path below.
        logger.warning("No metric provider configured. Skipping metrics fetch.")
        return {
            'memory_total': [], 'memory_free': [],
            'memory_available': [], 'cpu': [],
        }

    # Namespace rules of the project (namespace = hub), for stores that scope
    # by namespace rather than by labels (Google Cloud Monitoring on GKE).
    # Best-effort: never a reason for the metrics fetch to fail.
    if isinstance(getattr(provider, 'project_namespaces', None), (list, tuple)) \
            and hasattr(project_obj, 'log_rules_clean'):
        try:
            from integrations.schemas import _GCP_RESOURCE_FIELDS
            rules = project_obj.log_rules_clean()
            provider.project_namespaces = [str(v).lower() for f, v in (rules if isinstance(rules, list) else [])
                                           if _GCP_RESOURCE_FIELDS.get(f) == 'namespace_name']
        except Exception as exc:                            # noqa: BLE001
            logger.warning('namespace rules not applied to the metric provider: %s', exc)

    if project_name_str:
        labels['project_name'] = project_name_str
    if environment_str:
        labels['environment'] = environment_str
        
    metrics = {}
    
    def _series_key(labels):
        """Stable identity for one time series.

        Kubernetes metric templates aggregate ``by (service_name)``, so a
        four-service project returns four series that share every timestamp.
        Without an identity on each point, everything downstream that keyed on
        time alone silently collapsed them to one — see
        ``calculate_memory_usage``. ``series_id`` cannot serve: it is a VM-mode
        label that a ``sum by (service_name)`` result does not carry, so every
        Kubernetes series arrived as series_id 0.
        """
        labels = labels or {}
        for candidate in ('service_name', 'container', 'pod', 'instance', 'series_id'):
            value = labels.get(candidate)
            if value not in (None, ''):
                return str(value)
        if labels:
            return ','.join(f'{k}={v}' for k, v in sorted(labels.items()))
        return 'default'

    def _map_timeseries(ts_list, source_table):
        results = []
        for ts in ts_list:
            try:
                sid = int(ts.labels.get('series_id', 0))
            except (ValueError, TypeError):
                sid = 0

            key = _series_key(getattr(ts, 'labels', None))
            for p in ts.points:
                results.append({
                    'time': p.timestamp,
                    'value': p.value,
                    'series_id': sid,
                    'series_key': key,
                    'source_table': source_table
                })
        return results

    # Which queries the store refused. Each query is caught on its own: one
    # unmapped metric (Azure VM memory) must not cost the CPU series that
    # work, and a store that refuses everything must not read as "no
    # anomalies" (phase 3 review, MT-1 / CL-11). The outcome goes back to the
    # caller as metrics['_source_status'].
    failures = []
    attempts = [0]
    provider.last_search_notes = []

    def guarded(call, *args):
        attempts[0] += 1
        try:
            return call(*args) or []
        except MetricQueryError as exc:
            failures.append(str(exc))
            return []

    try:
        logger.info(f"Fetching metrics via {provider.__class__.__name__} for labels {labels}")
        
        ts = guarded(provider.query_range, 'node_memory_MemTotal_bytes', labels, start_time, end_time)
        metrics['memory_total'] = _map_timeseries(ts, 'node_memory_MemTotal_bytes')
        
        ts = guarded(provider.query_range, 'node_memory_MemFree_bytes', labels, start_time, end_time)
        metrics['memory_free'] = _map_timeseries(ts, 'node_memory_MemFree_bytes')
        
        ts = guarded(provider.query_range, 'node_memory_MemAvailable_bytes', labels, start_time, end_time)
        metrics['memory_available'] = _map_timeseries(ts, 'node_memory_MemAvailable_bytes')
        
        # CPU: use PromQL rate() expression when provider supports it.
        # node_cpu_seconds_total is a counter with per-core per-mode series;
        # computing rate server-side avoids mixing series in Python.
        if getattr(provider, 'topology_mode', 'vm') == 'kubernetes':
            # Kubernetes mode must NOT use the node-exporter expression below.
            # `node_cpu_seconds_total{mode="idle"}` is a node-level metric that
            # never carries organisation_name / project_name / environment, so
            # the selector matched nothing and every Kubernetes install got
            # zero CPU data points — silently, with the AI told
            # "0 CPU data points" and trend UNKNOWN.
            #
            # Going through query_range() lets the adapter substitute its
            # container-level template (sum by (service_name) over
            # rate(container_cpu_usage_seconds_total)). That yields cores/sec,
            # so scale by 100 to reach the percent semantics the rest of the
            # pipeline and the prompt assume — "% of one core" per service.
            ts = guarded(provider.query_range, 'node_cpu_seconds_total', labels, start_time, end_time)
            cpu_points = _map_timeseries(ts, 'cpu_usage_percent')
            for point in cpu_points:
                try:
                    point['value'] = round(float(point['value']) * 100, 2)
                except (TypeError, ValueError):
                    pass
            metrics['cpu'] = cpu_points
            # Pre-computed percentage — tasks.py then skips calculate_cpu_usage,
            # which is right: that helper differentiates a counter, and this is
            # already a rate. Running it would differentiate twice.
            metrics['cpu_usage_percent'] = cpu_points
            # Not a share of anything: cores used by all the service's
            # replicas, x100. 6 replicas at 0.25 cores read "150 %" and the
            # 80 % detector flagged a healthy service (phase 3 review MT-3).
            # The summary and the prompt label it, and saturation comes from
            # the throttling signal instead.
            metrics['cpu_unit'] = CPU_UNIT_CORE_PERCENT
        elif hasattr(provider, 'query_range_expr'):
            from integrations.promql import promql_matchers
            label_parts = promql_matchers(labels)
            idle_selector = f'mode="idle",{label_parts}' if label_parts else 'mode="idle"'
            cpu_expr = f'100 - (avg(rate(node_cpu_seconds_total{{{idle_selector}}}[5m])) * 100)'
            logger.info(f"Fetching CPU usage via PromQL: {cpu_expr}")
            ts = guarded(provider.query_range_expr, cpu_expr, start_time, end_time)
            metrics['cpu'] = _map_timeseries(ts, 'cpu_usage_percent')
            # Pre-computed percentage — store directly so tasks.py skips calculate_cpu_usage
            metrics['cpu_usage_percent'] = metrics['cpu']
        else:
            ts = guarded(provider.query_range, 'node_cpu_seconds_total', labels, start_time, end_time)
            metrics['cpu'] = _map_timeseries(ts, 'node_cpu_seconds_total')
            # CloudWatch and Datadog hand back a CPU percentage, not a
            # seconds counter: calculate_cpu_usage would differentiate it.
            if getattr(provider, 'cpu_is_percent', False) is True:
                metrics['cpu_usage_percent'] = metrics['cpu']

        # Container lifecycle (Kubernetes only).
        #
        # An OOMKill is a kubelet event, not an application log line — the
        # container's logs stop mid-stream with nothing explaining why. Without
        # this the AI sees a dependency that abruptly stopped answering and
        # correctly describes the cascade while never naming the cause.
        # Measured on the chaos suite: the two memory-exhaustion scenarios both
        # failed exactly that way while every other signal-based scenario
        # passed.
        if getattr(provider, 'topology_mode', 'vm') == 'kubernetes':
            k8s_failures = []
            metrics['container_lifecycle'] = _fetch_container_lifecycle(
                provider, labels, start_time, end_time, failures=k8s_failures)
            if k8s_failures:
                note_partial(provider, f'{len(k8s_failures)} Kubernetes state queries failed '
                                       '(restarts, rollouts or replica counts may be missing)')

            # Peak single-pod utilisation per service.
            #
            # The aggregates above answer "how much capacity is this service
            # using"; this answers "is any one of its pods about to die", which
            # the sum cannot show. See K8S_PEAK_POD_EXPR_TEMPLATES.
            peak = _fetch_peak_pod_metrics(provider, labels, start_time, end_time)
            metrics.update(peak)
            unlabelled = _fetch_unlabelled_pods(provider, labels, start_time, end_time)
            if unlabelled:
                metrics['container_lifecycle'] = {**(metrics.get('container_lifecycle') or {}),
                                                  'unlabelled_pods': unlabelled}

        # JVM garbage collection, any topology: best-effort, never fails the
        # batch. Client C2 (J2): a Java service in repeated full GCs was named
        # but GC never was; the agent's GC metrics are the only evidence.
        metrics.update(_fetch_jvm_gc(provider, labels, start_time, end_time, project_obj))

    except Exception as e:
        logger.error(f"Error fetching metrics from provider: {e}", exc_info=True)
        metrics = {
            'memory_total': [], 'memory_free': [], 'memory_available': [], 'cpu': []
        }
        failures.append(f'the metrics fetch failed ({type(e).__name__})')
        attempts[0] = max(attempts[0], len(failures))

    metrics['_source_status'] = metric_source_status(
        failures, attempts[0], getattr(provider, 'last_search_notes', None))
    return metrics


def metric_source_status(failures, attempts, notes=None):
    """``{'status': 'ok' | 'unavailable' | 'partial', 'detail': str}`` for
    the batch's data_sources entry. Unavailable: every query was refused."""
    notes = [n for n in (notes or []) if n]
    if failures and len(failures) >= attempts:
        return {'status': 'unavailable', 'detail': failures[0]}
    if failures:
        return {'status': 'partial',
                'detail': f'{len(failures)} of {attempts} metric queries failed: {failures[0]}'}
    if notes:
        return {'status': 'partial', 'detail': '; '.join(notes)}
    return {'status': 'ok', 'detail': ''}


def _coerce_datetime(value):
    """Accept a datetime or an ISO-8601 string, return an aware datetime.

    Metric points carry ``time`` as a real ``datetime`` while they are in the
    pipeline (``fetch_metrics_with_provider`` copies ``TimeSeriesPoint.timestamp``
    straight through, and ``calculate_cpu_usage`` subtracts them), but the same
    records come back as ISO strings once a batch has been serialised to JSON
    and read again. Anomaly detection previously assumed strings only and did
    ``value.replace('Z', '+00:00')``, which on a datetime means
    ``datetime.replace()`` — a TypeError, swallowed by a bare except. Every
    point was therefore judged invalid and anomaly detection silently returned
    nothing while logging "No valid timestamps found".

    Returns None for anything unusable so callers can skip the point.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)
    return None


def _iso_timestamp(value):
    """Render a metric timestamp as a string for the summary payload.

    The summary is stored in ``AIAnalyzedBatch.data``, a JSONField, so a raw
    datetime here fails to serialise on save. Emitted timestamps used to be
    copied verbatim from the input, meaning the only reason this never blew up
    is that anomaly detection never produced any output.
    """
    coerced = _coerce_datetime(value)
    return coerced.isoformat() if coerced else ''


def _fetch_peak_pod_metrics(provider, labels, start_time, end_time):
    """Worst-pod memory % and CPU cores per service, as point lists.

    Returns ``{'peak_pod_memory_percent': [...], 'peak_pod_cpu_cores': [...]}``
    keyed the same way as every other series so the rest of the pipeline treats
    them normally — including ``series_key``, which is what lets the summary and
    the prompt name the service.

    Best-effort and never raises: a missing peak view must not cost the batch
    its ordinary metrics.
    """
    from integrations.adapters.prometheus import K8S_PEAK_POD_EXPR_TEMPLATES

    out = {}
    if not hasattr(provider, 'query_range_expr'):
        return out

    from integrations.promql import promql_matchers
    label_str = promql_matchers(labels)
    from integrations.adapters.prometheus import k8s_container_expr

    for key, template in K8S_PEAK_POD_EXPR_TEMPLATES.items():
        try:
            series = provider.query_range_expr(
                k8s_container_expr(template, label_str), start_time, end_time)
        except Exception as exc:                            # noqa: BLE001
            logger.warning('peak-pod query %s failed: %s', key, exc)
            out[key] = []
            continue

        points = []
        for ts in series or []:
            svc = (getattr(ts, 'labels', {}) or {}).get('service_name') or 'default'
            for pt in ts.points:
                points.append({
                    'time': pt.timestamp,
                    'value': pt.value,
                    'series_key': str(svc),
                    'series_id': 0,
                    'source_table': key,
                })
        out[key] = points

    return out


# The busiest pods among containers with no service label.
#
# Client C1 (I7): a bare Pod (a nightly reindex, no Deployment) took the CPU.
# The documented pod-name relabel gave it no service_name, so it summed into
# "unlabelled containers" and the analysis explained the bucket away as an
# aggregate instead of naming the workload. The pod names let it name it.
UNLABELLED_TOP_PODS_TEMPLATE = (
    'topk(3, sum by (namespace, pod) '
    '(rate(container_cpu_usage_seconds_total{{{labels}}}[5m])))'
)


def _fetch_unlabelled_pods(provider, labels, start_time, end_time):
    """[{'pod', 'namespace', 'peak_cores'}], busiest first, at most 3.
    Best-effort: [] on any failure."""
    if not hasattr(provider, 'query_range_expr'):
        return []
    from integrations.adapters.prometheus import CONTAINER_LEVEL_MATCHER, ROOT_CGROUP_MATCHER
    from integrations.promql import promql_matchers
    matchers = [m for m in (promql_matchers(labels), ROOT_CGROUP_MATCHER, CONTAINER_LEVEL_MATCHER,
                            'service_name=""', 'pod!=""') if m]
    try:
        series = provider.query_range_expr(
            UNLABELLED_TOP_PODS_TEMPLATE.format(labels=",".join(matchers)), start_time, end_time)
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('unlabelled pods query failed: %s', exc)
        return []
    peaks = {}
    for ts in series or []:
        tags = getattr(ts, 'labels', {}) or {}
        values = [p.value for p in getattr(ts, 'points', []) or [] if isinstance(p.value, (int, float))
                  and p.value == p.value]
        if not tags.get('pod') or not values:
            continue
        key = (tags.get('namespace') or '', tags['pod'])
        peaks[key] = max(peaks.get(key, 0), max(values))
    top = sorted(peaks.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return [{'pod': pod, 'namespace': ns, 'peak_cores': round(v, 2)} for (ns, pod), v in top if v >= 0.01]


# JVM garbage collection.
#
# Metric names, in the order they are tried for each service (``or`` keeps
# the first that answers), with the factor that turns their ``_sum`` into
# seconds:
#   jvm_gc_duration_seconds                        OpenTelemetry Java agent 2.x (jvm.gc.duration)
#   process_runtime_jvm_gc_duration_seconds        older OpenTelemetry Java agent
#   process_runtime_jvm_gc_duration_milliseconds   the same, exported in milliseconds
#   jvm_gc_collection_seconds                      Prometheus simpleclient_hotspot
#   jvm_gc_pause_seconds                           Micrometer
JVM_GC_METRICS = (
    ('jvm_gc_duration_seconds', 1.0),
    ('process_runtime_jvm_gc_duration_seconds', 1.0),
    ('process_runtime_jvm_gc_duration_milliseconds', 0.001),
    ('jvm_gc_collection_seconds', 1.0),
    ('jvm_gc_pause_seconds', 1.0),
)
# Concurrent collector work (G1 concurrent cycle, ZGC, Shenandoah) is not a
# pause. Agents that report it name it in an action or collector label; a
# series without the label matches a negative regex, so this only removes
# what is labelled concurrent. What the agent does not separate stays in.
JVM_GC_NOT_CONCURRENT = ('jvm_gc_action!~"(?i).*concurrent.*",jvm_gc_name!~"(?i).*concurrent.*",'
                         'gc!~"(?i).*concurrent.*",action!~"(?i).*concurrent.*",'
                         'cause!~"(?i).*concurrent.*"')


def _jvm_gc_expr(selectors, part):
    """Worst single JVM per service: % of wall time in GC (``part='sum'``)
    or collections per minute (``part='count'``), across every metric name
    and every selector, joined with ``or``."""
    terms = []
    for selector in selectors:
        for name, to_seconds in JVM_GC_METRICS:
            scale = f'{to_seconds * 100:g}' if part == 'sum' else '60'
            terms.append(
                'max by (service_name, job) (sum by (service_name, job, instance, pod) '
                f'(rate({name}_{part}{{{selector}}}[5m]))) * {scale}')
    return ' or '.join(f'({t})' for t in terms)


def _promql_regex_value(values):
    """``a|b`` for a PromQL regex string: each value regex-escaped, then
    escaped for the double-quoted string."""
    import re
    return '|'.join(re.escape(str(v)).replace('\\', '\\\\').replace('"', '\\"') for v in values)


def _project_namespaces_and_services(project_obj):
    """(namespaces, services) the project declares: namespace log rules and
    deployment namespaces; its service names. Empty when unknown."""
    namespaces, services = [], []
    if project_obj is None:
        return namespaces, services
    try:
        from integrations.schemas import _GCP_RESOURCE_FIELDS
        rules = project_obj.log_rules_clean() if hasattr(project_obj, 'log_rules_clean') else []
        namespaces += [str(v) for f, v in (rules if isinstance(rules, list) else [])
                       if _GCP_RESOURCE_FIELDS.get(f) == 'namespace_name']
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('JVM GC: namespace rules unreadable: %s', exc)
    try:
        namespaces += [n for n in project_obj.deployments.exclude(namespace='')
                       .values_list('namespace', flat=True)]
    except Exception:                                           # noqa: BLE001
        pass
    try:
        services = [n for n in project_obj.services.values_list('name', flat=True) if n]
    except Exception:                                           # noqa: BLE001
        services = []
    return sorted(set(namespaces)), sorted(set(services))


def _jvm_gc_points(series, source_table):
    points = []
    for ts in series or []:
        tags = getattr(ts, 'labels', {}) or {}
        # OTel sets job to "<namespace>/<service>" or "<service>".
        svc = tags.get('service_name') or str(tags.get('job') or '').rsplit('/', 1)[-1] or 'default'
        for pt in getattr(ts, 'points', []) or []:
            if isinstance(pt.value, (int, float)) and pt.value == pt.value:
                points.append({'time': pt.timestamp, 'value': pt.value, 'series_key': str(svc),
                               'series_id': 0, 'source_table': source_table})
    return points


def _fetch_jvm_gc(provider, labels, start_time, end_time, project_obj=None):
    """``{'jvm_gc_time_percent': [...], 'jvm_gc_collections_per_minute': [...],
    'jvm_gc_matched_by': 'project labels' | 'namespace and service'}`` or {}.

    First with the project's labels. When that finds nothing, and only then,
    a narrow fallback for JVM metrics an agent pushed without them (OTLP
    into Mimir): the project's own services, and only when the project
    declares a namespace and the series carry a ``namespace`` label. Never
    wider. Best-effort: {} on any failure.
    """
    if not hasattr(provider, 'query_range_expr'):
        return {}
    from integrations.promql import promql_matchers
    try:
        label_str = promql_matchers(labels)
    except ValueError:
        return {}
    attempts = []
    if label_str:
        attempts.append(('project labels', [f'{label_str},{JVM_GC_NOT_CONCURRENT}']))
    namespaces, services = _project_namespaces_and_services(project_obj)
    if namespaces and services:
        ns = f'namespace=~"{_promql_regex_value(namespaces)}"'
        svc = _promql_regex_value(services)
        attempts.append(('namespace and service', [
            f'{ns},service_name=~"{svc}",{JVM_GC_NOT_CONCURRENT}',
            f'{ns},job=~"(.+/)?({svc})",{JVM_GC_NOT_CONCURRENT}',
        ]))
    for matched_by, selectors in attempts:
        try:
            share = provider.query_range_expr(_jvm_gc_expr(selectors, 'sum'), start_time, end_time)
        except Exception as exc:                                # noqa: BLE001
            logger.warning('JVM GC time query failed (%s): %s', matched_by, exc)
            continue
        share_points = _jvm_gc_points(share, 'jvm_gc_time_percent')
        if not share_points:
            continue
        try:
            count = provider.query_range_expr(_jvm_gc_expr(selectors, 'count'), start_time, end_time)
        except Exception as exc:                                # noqa: BLE001
            logger.warning('JVM GC count query failed (%s): %s', matched_by, exc)
            count = []
        return {'jvm_gc_time_percent': share_points,
                'jvm_gc_collections_per_minute': _jvm_gc_points(count, 'jvm_gc_collections_per_minute'),
                'jvm_gc_matched_by': matched_by}
    return {}


# Above this share of wall time in GC a JVM is flagged. Set from what the
# JVM itself treats as normal, not from any benchmark incident: G1, the
# default collector, sizes the heap to keep GC under 1/(1+GCTimeRatio) of
# the time, GCTimeRatio=12 by default, "a target with about 8% of the time
# to be spent in garbage collection" (Java SE 21 GC Tuning Guide, G1 tunable
# defaults: https://docs.oracle.com/en/java/javase/21/gctuning/garbage-first-garbage-collector-tuning.html).
# The Parallel collector's default target is 1 % (GCTimeRatio=99). A JVM
# past 10 % is beyond the default target of either collector.
JVM_GC_TIME_THRESHOLD_PERCENT = 10.0


def _jvm_gc_summary(raw_metrics):
    share = raw_metrics.get('jvm_gc_time_percent') or []
    if not share:
        return {}
    counts = raw_metrics.get('jvm_gc_collections_per_minute') or []
    by_svc, peak_count = {}, {}
    for p in share:
        by_svc.setdefault(p.get('series_key', 'default'), []).append(p['value'])
    for p in counts:
        key = p.get('series_key', 'default')
        peak_count[key] = max(peak_count.get(key, 0), p['value'])
    services = []
    for svc, vals in by_svc.items():
        peak = round(max(vals), 1)
        services.append({'service': svc, 'peak_percent': peak,
                         'avg_percent': round(sum(vals) / len(vals), 1),
                         'peak_collections_per_minute': round(peak_count[svc], 1) if svc in peak_count else None,
                         'over_threshold': peak > JVM_GC_TIME_THRESHOLD_PERCENT})
    services.sort(key=lambda s: s['peak_percent'], reverse=True)
    return {'threshold_percent': JVM_GC_TIME_THRESHOLD_PERCENT,
            'matched_by': raw_metrics.get('jvm_gc_matched_by'), 'services': services}


def _fetch_container_lifecycle(provider, labels, start_time, end_time, failures=None):
    """What Kubernetes did around the batch: restarts and their reason,
    containers that cannot start, rollouts, scale changes, missing replicas.
    See integrations.kubernetes_state. Never raises; failed queries are
    appended to ``failures``."""
    from integrations.kubernetes_state import fetch_kubernetes_state
    try:
        return fetch_kubernetes_state(provider, labels, start_time, end_time, failures=failures)
    except Exception as exc:                           # noqa: BLE001
        logger.warning('kubernetes state fetch failed: %s', exc)
        return {'terminated': [], 'restarts': {}}


def calculate_memory_usage(metrics):
    """Calculate memory usage percentage per series from total and available.

    Keyed on ``(series, timestamp)``, not timestamp alone. In Kubernetes mode
    the memory templates aggregate ``by (service_name)``, so every service in a
    project reports at the same instants — and a dict keyed only by time kept
    whichever service happened to be iterated last, throwing the rest away
    without a word. A four-service project therefore reported one service's
    memory as the whole project's.

    That is why memory anomalies never fired on the validation cluster: the one
    container climbing towards its limit was overwritten by a quiet sibling,
    so the series handed to anomaly detection sat flat while the kubelet was
    about to OOMKill the pod. Worse, nothing guaranteed the surviving ``total``
    and ``available`` came from the SAME service, so the percentage could be
    two unrelated containers divided by each other.

    Output points keep ``series_key`` so callers can reason per service; the
    list is no longer a single project-wide series.
    """
    memory_usage = []

    def _by_series(rows):
        grouped = {}
        for m in rows or []:
            grouped.setdefault(m.get('series_key', 'default'), {})[m['time']] = m['value']
        return grouped

    totals = _by_series(metrics.get('memory_total', []))
    availables = _by_series(metrics.get('memory_available', []))

    for series_key in sorted(set(totals) & set(availables)):
        total_metrics = totals[series_key]
        available_metrics = availables[series_key]
        for timestamp in set(total_metrics) & set(available_metrics):
            mem_total = total_metrics[timestamp]
            mem_available = available_metrics[timestamp]
            if mem_total > 0:
                usage_percent = round(100.0 * (mem_total - mem_available) / mem_total, 2)
                memory_usage.append({
                    'time': timestamp,
                    'value': usage_percent,
                    'series_key': series_key,
                    'source_table': 'memory_usage_percent'
                })

    return memory_usage


def calculate_cpu_usage(cpu_metrics):
    """
    Calculate CPU usage percentage from counter-style CPU seconds metrics.

    Each series_id represents one CPU core. The number of cores is derived
    from the data itself (count of distinct series_ids) rather than hardcoded.
    """
    cpu_usage = []

    series_data = defaultdict(list)
    for metric in cpu_metrics:
        series_data[metric['series_id']].append({
            'time': metric['time'],
            'value': metric['value']
        })

    num_cores = max(len(series_data), 1)

    for series_id in series_data:
        series_data[series_id].sort(key=lambda x: x['time'])

    for series_id, metrics in series_data.items():
        if len(metrics) < 2:
            continue

        for i in range(1, len(metrics)):
            prev = metrics[i-1]
            current = metrics[i]

            try:
                time_diff = (current['time'] - prev['time']).total_seconds()
                if time_diff <= 0:
                    continue

                delta_value = current['value'] - prev['value']
                usage_percent = (delta_value / (time_diff * num_cores)) * 100

                cpu_usage.append({
                    'time': current['time'],
                    'value': round(usage_percent, 2),
                    'series_id': series_id,
                    'source_table': 'node_cpu_usage_percent'
                })

            except Exception as e:
                logger.warning(f"Error on series {series_id}: {str(e)}")
                continue

    return cpu_usage


def preprocess_metrics_for_ai(raw_metrics: dict, time_window_minutes: int = 5) -> dict:
    """
    Convert raw metrics into a compact AI-friendly summary.
    Detects anomalies, calculates trends, and provides correlation windows.
    """
    memory_usage = raw_metrics.get('memory_usage_percent', [])
    cpu_usage = raw_metrics.get('cpu_usage_percent', [])
    memory_total = raw_metrics.get('memory_total', [])
    memory_available = raw_metrics.get('memory_available', [])
    
    def calculate_trend(values: list) -> str:
        if len(values) < 2:
            return "UNKNOWN"
        try:
            first_half = sum(v['value'] for v in values[:len(values)//2]) / max(1, len(values)//2)
            second_half = sum(v['value'] for v in values[len(values)//2:]) / max(1, len(values) - len(values)//2)
            diff = second_half - first_half
            if diff > 5:
                return "INCREASING"
            elif diff < -5:
                return "DECREASING"
            return "STABLE"
        except (KeyError, TypeError, ZeroDivisionError):
            return "UNKNOWN"
    
    def _detect_anomalies_one_series(values: list, threshold_percent: float,
                                     metric_type: str = "high_usage") -> list:
        """Detect periods of high usage with duration tracking, for ONE series.

        Must not be handed a mix of series: it sorts by time and walks the
        points looking for sustained runs, so interleaved services turn one
        service's climb into an alternating above/below sawtooth and every
        anomaly is cut to a single sample. ``detect_anomalies`` does the
        splitting.
        """
        if not values:
            return []
        
        anomalies = []
        in_anomaly = False
        anomaly_start = None
        peak_value = 0
        
        def parse_timestamp(v):
            return _coerce_datetime(v.get('time'))

        valid_values = [v for v in values if parse_timestamp(v) is not None]
        if not valid_values:
            logger.warning(f"No valid timestamps found in {len(values)} metric values")
            return []
        
        sorted_values = sorted(valid_values, key=lambda v: parse_timestamp(v))
        
        above_threshold_count = sum(1 for v in sorted_values if v.get('value', 0) > threshold_percent)
        total_count = len(sorted_values)
        
        if total_count > 0 and (above_threshold_count / total_count) >= 0.8:
            try:
                all_values_above = [v.get('value', 0) for v in sorted_values if v.get('value', 0) > threshold_percent]
                peak_val = max(all_values_above) if all_values_above else 0
                avg_val = sum(all_values_above) / len(all_values_above) if all_values_above else 0
                
                start_time = parse_timestamp(sorted_values[0])
                end_time = parse_timestamp(sorted_values[-1])

                if not start_time or not end_time:
                    return []

                if start_time > end_time:
                    start_time, end_time = end_time, start_time

                # Derived from the parsed values rather than copied from the
                # input, so the payload is a JSON-safe string either way.
                first_timestamp = _iso_timestamp(start_time)
                last_timestamp = _iso_timestamp(end_time)

                duration_seconds = int((end_time - start_time).total_seconds())

                min_safe_time = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
                safe_start = max(start_time - timedelta(minutes=time_window_minutes), min_safe_time)
                
                anomalies.append({
                    "start_time": first_timestamp,
                    "end_time": last_timestamp,
                    "peak_value": round(peak_val, 1),
                    "avg_value": round(avg_val, 1),
                    "duration_seconds": max(duration_seconds, 0),
                    "type": f"{metric_type}_sustained",
                    "sustained": True,
                    "coverage_percent": round(100 * above_threshold_count / total_count, 1),
                    "correlation_window": {
                        "start": safe_start.isoformat(),
                        "end": (end_time + timedelta(minutes=time_window_minutes)).isoformat()
                    }
                })
                return anomalies
            except Exception as e:
                logger.warning(f"Error detecting sustained anomaly: {e}")
        
        for i, v in enumerate(sorted_values):
            value = v.get('value', 0)
            timestamp = v.get('time', '')
            
            if value > threshold_percent:
                if not in_anomaly:
                    in_anomaly = True
                    anomaly_start = timestamp
                    peak_value = value
                else:
                    peak_value = max(peak_value, value)
            else:
                if in_anomaly:
                    try:
                        if anomaly_start and i > 0:
                            start_time = _coerce_datetime(anomaly_start)
                            end_time = _coerce_datetime(sorted_values[i-1]['time'])
                            if not start_time or not end_time:
                                raise ValueError('unparseable anomaly boundary')
                            duration_seconds = int((end_time - start_time).total_seconds())

                            min_safe_time = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
                            safe_start = max(start_time - timedelta(minutes=time_window_minutes), min_safe_time)

                            anomalies.append({
                                "start_time": _iso_timestamp(anomaly_start),
                                "end_time": _iso_timestamp(sorted_values[i-1]['time']),
                                "peak_value": round(peak_value, 1),
                                "duration_seconds": max(duration_seconds, 0),
                                "type": metric_type,
                                "sustained": False,
                                "correlation_window": {
                                    "start": safe_start.isoformat(),
                                    "end": (end_time + timedelta(minutes=time_window_minutes)).isoformat()
                                }
                            })
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Error calculating anomaly duration: {e}")
                    
                    in_anomaly = False
                    anomaly_start = None
                    peak_value = 0
        
        if in_anomaly and anomaly_start and sorted_values:
            try:
                start_time = _coerce_datetime(anomaly_start)
                end_time = _coerce_datetime(sorted_values[-1]['time'])
                if not start_time or not end_time:
                    raise ValueError('unparseable trailing anomaly boundary')
                duration_seconds = int((end_time - start_time).total_seconds())

                min_safe_time = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
                safe_start = max(start_time - timedelta(minutes=time_window_minutes), min_safe_time)

                anomalies.append({
                    "start_time": _iso_timestamp(anomaly_start),
                    "end_time": _iso_timestamp(sorted_values[-1]['time']),
                    "peak_value": round(peak_value, 1),
                    "duration_seconds": max(duration_seconds, 0),
                    "type": metric_type,
                    "sustained": False,
                    "correlation_window": {
                        "start": safe_start.isoformat(),
                        "end": (end_time + timedelta(minutes=time_window_minutes)).isoformat()
                    }
                })
            except (ValueError, TypeError) as e:
                logger.warning(f"Error calculating final anomaly duration: {e}")
        
        return anomalies[-5:] if len(anomalies) > 5 else anomalies

    def detect_anomalies(values: list, threshold_percent: float,
                         metric_type: str = "high_usage") -> list:
        """Detect high-usage periods, one series at a time.

        A project's metrics are per-service, and a real incident is usually ONE
        service misbehaving while its siblings stay healthy. Run over the
        combined list, the detector sees that service's high samples separated
        by its neighbours' low ones and finds nothing sustained — the reason
        anomaly counts came back as zero on the validation cluster even while a
        container was climbing towards an OOMKill.

        Each anomaly is tagged with the service it belongs to, which is the
        part the AI actually needs: "cache memory is saturating" is a diagnosis,
        "the project has high memory" is not.
        """
        if not values:
            return []

        by_series = {}
        for v in values:
            by_series.setdefault(v.get('series_key', 'default'), []).append(v)

        found = []
        for series_key, series_values in sorted(by_series.items()):
            for anomaly in _detect_anomalies_one_series(
                    series_values, threshold_percent, metric_type):
                # 'default' is the bucket for series that carry no service
                # label — the single node-level series in VM mode, and in
                # Kubernetes the containers the relabeling missed. Attaching it
                # as a service name would invent one, so it is left off and the
                # anomaly reads as project-wide, which is what it is.
                if series_key != 'default':
                    anomaly['service'] = series_key
                found.append(anomaly)

        # Worst first, so a truncated list keeps the most severe.
        found.sort(key=lambda a: (a.get('peak_value') or 0), reverse=True)
        return found[:10]

    def safe_stats(values: list) -> dict:
        if not values:
            return {"min": None, "max": None, "avg": None, "current": None, "trend": "UNKNOWN"}
        
        try:
            nums = [v.get('value', 0) for v in values if isinstance(v.get('value'), (int, float))]
            if not nums:
                return {"min": None, "max": None, "avg": None, "current": None, "trend": "UNKNOWN"}
            
            return {
                "min": round(min(nums), 1),
                "max": round(max(nums), 1),
                "avg": round(sum(nums) / len(nums), 1),
                "current": round(nums[-1], 1),
                "trend": calculate_trend(values)
            }
        except (TypeError, ZeroDivisionError):
            return {"min": None, "max": None, "avg": None, "current": None, "trend": "UNKNOWN"}
    
    # Get time range.
    #
    # Coerce before sorting. This list is built from two independent metric
    # sources, so it can hold datetimes and ISO strings together — and
    # `sorted()` on a mixed list raises TypeError ('<' not supported between
    # instances of 'datetime.datetime' and 'str'), which would abort the whole
    # summary rather than just the time range. Unparseable entries are dropped
    # instead of poisoning the comparison.
    all_times = [
        coerced for coerced in (
            _coerce_datetime(m.get('time')) for m in memory_usage + cpu_usage
        )
        if coerced is not None
    ]
    if all_times:
        all_times.sort()
        time_range = {
            "start": all_times[0].isoformat(),
            "end": all_times[-1].isoformat(),
        }
    else:
        time_range = {"start": None, "end": None}
    
    # Sum one point per series rather than reading point zero. With per-service
    # series, ``memory_total[0]`` was whichever service the provider listed
    # first — reported as the project's total memory, so a four-service project
    # understated its capacity by roughly 4x.
    total_memory_gb = None
    if memory_total:
        try:
            first_per_series = {}
            for m in memory_total:
                first_per_series.setdefault(m.get('series_key', 'default'), m['value'])
            total_memory_gb = round(sum(first_per_series.values()) / 1_073_741_824, 2)
        except (KeyError, TypeError, IndexError):
            pass

    # Per-service breakdown. The aggregate stats below mix every service
    # together, which is how a single saturating container disappears into a
    # healthy project average; this names the service instead.
    def _per_service(values):
        grouped = {}
        for v in values or []:
            grouped.setdefault(v.get('series_key', 'default'), []).append(v)
        return {key: safe_stats(rows) for key, rows in sorted(grouped.items())}

    per_service = {
        "memory_usage_percent": _per_service(memory_usage),
        "cpu_usage_percent": _per_service(cpu_usage),
    }

    # Peak single-pod view, and anomaly detection ON it.
    #
    # Running detection only on the aggregate is what lets a hot replica hide:
    # three pods at 95/20/20 sum to ~45% and never cross the 75% threshold. The
    # same per-series detector is reused, so a peak anomaly still names its
    # service.
    peak_memory = raw_metrics.get('peak_pod_memory_percent') or []
    peak_cpu = raw_metrics.get('peak_pod_cpu_cores') or []
    # Pass container lifecycle through untouched — it is already small and
    # categorical, and summarising it would lose the reason string that makes
    # it useful.
    lifecycle = raw_metrics.get('container_lifecycle') or {}

    memory_anomalies, steady_memory = _split_steady_memory(
        detect_anomalies(memory_usage, 75.0, "memory_high_usage"), memory_usage, lifecycle)
    peak_anomalies, steady_peak = _split_steady_memory(
        detect_anomalies(peak_memory, 75.0, "peak_pod_memory_high_usage"), peak_memory, lifecycle)

    peak_pod = {
        "memory_percent": _per_service(peak_memory),
        "cpu_cores": _per_service(peak_cpu),
        "memory_anomalies": peak_anomalies,
    }

    return {
        "container_lifecycle": lifecycle,
        "jvm_gc": _jvm_gc_summary(raw_metrics),
        "per_service": per_service,
        "peak_pod": peak_pod,
        "time_range": time_range,
        "data_points": {
            "memory": len(memory_usage),
            "cpu": len(cpu_usage)
        },
        "memory": {
            "total_gb": total_memory_gb,
            "usage_percent": safe_stats(memory_usage),
            "anomalies": memory_anomalies,
            # Near the limit, flat, no restarts: context, not an incident.
            "steady_near_limit": _merge_steady(steady_memory, steady_peak),
        },
        "cpu": _cpu_summary(cpu_usage, raw_metrics.get('cpu_unit'), safe_stats, detect_anomalies),
    }


# A memory level that sits still is a sizing fact, not an incident. Client C2
# (phase 3, 2026-11-16): pods held 80-90 % of their limits all day, every
# batch flagged them as sustained high memory, and that noise outranked the
# real fault (and once went CRITICAL on a healthy rollout). A series counts as
# steady when it moved no more than STEADY_MEMORY_RANGE points over the window,
# stayed under STEADY_MEMORY_CEILING (above it a replica is an OOMKill
# candidate whatever its trend), and its service did not restart. Only used
# when Kubernetes lifecycle data is present, so "no restart" is a fact.
STEADY_MEMORY_RANGE = 3.0
STEADY_MEMORY_CEILING = 95.0


def _service_restarted(service, lifecycle):
    names = set((lifecycle.get('restarts') or {}).keys())
    names.update(t.get('container', '') for t in lifecycle.get('terminated') or [])
    if not service:
        return bool(names)
    svc = str(service).lower()
    return any(n and (n.lower() == svc or svc in n.lower() or n.lower() in svc) for n in names)


def _split_steady_memory(anomalies, values, lifecycle):
    """``(anomalies, steady)``: sustained memory anomalies on a flat series
    with no restart move to ``steady``; growth, peaks near the limit, OOM
    kills and restarts stay anomalies."""
    if not anomalies or not isinstance(lifecycle, dict) or 'restarts' not in lifecycle:
        return anomalies, []
    by_series = {}
    for v in values or []:
        if isinstance(v.get('value'), (int, float)):
            by_series.setdefault(v.get('series_key', 'default'), []).append(v['value'])
    kept, steady = [], []
    for a in anomalies:
        key = a.get('service') or 'default'
        nums = by_series.get(key) or []
        flat = (a.get('sustained') and nums and max(nums) - min(nums) <= STEADY_MEMORY_RANGE
                and max(nums) < STEADY_MEMORY_CEILING)
        if flat and not _service_restarted(a.get('service'), lifecycle):
            steady.append({'service': a.get('service') or 'default',
                           'level_percent': round(sum(nums) / len(nums), 1),
                           'min': round(min(nums), 1), 'max': round(max(nums), 1)})
        else:
            kept.append(a)
    return kept, steady


def _merge_steady(*lists):
    """One entry per service, the highest level wins."""
    out = {}
    for entry in (e for lst in lists for e in lst):
        cur = out.get(entry['service'])
        if cur is None or entry['level_percent'] > cur['level_percent']:
            out[entry['service']] = entry
    return sorted(out.values(), key=lambda e: e['level_percent'], reverse=True)[:10]


def _cpu_summary(cpu_usage, unit, safe_stats, detect_anomalies):
    """CPU block of the metrics summary. A real percentage (node CPU, a
    provider's utilisation) is checked against 80 %; Kubernetes core-percent
    is not a share of a limit, so it gets no threshold anomaly and says its
    unit (phase 3 review MT-3)."""
    if unit == CPU_UNIT_CORE_PERCENT:
        return {"usage_percent": safe_stats(cpu_usage), "anomalies": [], "unit": unit}
    return {"usage_percent": safe_stats(cpu_usage),
            "anomalies": detect_anomalies(cpu_usage, 80.0, "cpu_high_usage")}


def clean_json(obj):
    """Recursively clean JSON to remove NaN, Inf, and null characters."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    elif isinstance(obj, str):
        return obj.replace('\u0000', '')
    elif isinstance(obj, dict):
        return {k: clean_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json(v) for v in obj]
    else:
        return obj
