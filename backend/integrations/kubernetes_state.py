"""What Kubernetes itself did around an incident, from kube-state-metrics.

Logs and cAdvisor metrics show what the application went through; they do
not show what was done TO it. On Online Boutique (production scenarios,
2026-11-02) that gap decided the answer twice:

* B2 — checkout redeployed with a wrong payment address. The logs say
  "checkout cannot reach payments", and the analysis blamed payments: it
  never learnt that checkout had just been rolled out with a new config.
* B5 — payments rolled to an image tag that does not exist. No pod was
  left to log anything; the rollout and the ImagePullBackOff were the whole
  story, and neither reached the analysis.

So, per batch, this reads from kube-state-metrics:

* restarts in the window and why the container last terminated (OOMKilled);
* containers stuck before starting (ImagePullBackOff, CrashLoopBackOff,
  CreateContainerConfigError, ...);
* rollouts and scale changes of Deployments / StatefulSets / DaemonSets in
  the window and the half hour before it, with the image change when there
  was one — "spec changed, same image" is how a config or environment change
  shows up;
* workloads short of available replicas.

Two joins the series need:

* **Namespace.** kube-state-metrics is its own exporter: its series carry
  ``namespace`` / ``pod`` / ``container`` but none of the organisation,
  project or environment labels the customer's relabeling puts on cAdvisor.
  The project's namespaces are therefore read off its cAdvisor series, which
  keep ``namespace``. Only when that finds nothing does the environment name
  stand in for the namespace (the mapping the documented recipes use). The
  boutique's agents say ``environment=production`` for namespace
  ``boutique``, which the environment-as-namespace guess missed entirely.
* **Workload.** Containers are often all called ``server`` or ``app`` (every
  Online Boutique service is ``server``), so a container name alone says
  "server restarted 3 times". Names are reported per workload, taken from
  the pod name.

Best-effort throughout: kube-state-metrics may not be scraped, and every
query failure leaves its part empty. Never raises.
"""

import logging
import re
from datetime import timedelta, timezone

logger = logging.getLogger(__name__)

# How far before the window a rollout or scale change is still reported: a
# bad deploy usually lands a few minutes before the errors it causes.
CHANGE_LOOKBACK = timedelta(minutes=30)

# Waiting reasons that are a problem rather than a normal start.
_BAD_WAITING = {
    'CrashLoopBackOff', 'ErrImagePull', 'ImagePullBackOff', 'InvalidImageName',
    'CreateContainerConfigError', 'CreateContainerError', 'RunContainerError',
}

# Container names that say nothing about what runs in them.
_GENERIC_CONTAINERS = {'server', 'app', 'main', 'application', 'container'}

# kind -> (generation metric, desired replicas metric or None, workload label)
_WORKLOAD_KINDS = {
    'Deployment': ('kube_deployment_metadata_generation', 'kube_deployment_spec_replicas', 'deployment'),
    'StatefulSet': ('kube_statefulset_metadata_generation', 'kube_statefulset_replicas', 'statefulset'),
    'DaemonSet': ('kube_daemonset_metadata_generation', None, 'daemonset'),
}

_DNS_LABEL = re.compile(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?')

_LIMITS = {'terminated': 6, 'waiting': 6, 'changes': 8, 'unavailable': 6, 'stuck': 6, 'throttled': 6}

# Share of CPU periods in which the kernel paused a service for exceeding its
# CPU limit, worth telling the AI about.
THROTTLED_PERCENT = 25


def workload_name(pod, container=''):
    """``checkout-7d9f8c6b5-x2k4q`` -> ``checkout`` (Deployment),
    ``db-0`` -> ``db`` (StatefulSet), ``agent-x2k4q`` -> ``agent`` (DaemonSet).

    With a container other than the workload's own (a sidecar), the
    container is appended: ``checkout/istio-proxy``.
    """
    pod = pod or ''
    container = container or ''
    for pattern in (r'^(.+)-[a-z0-9]{6,10}-[a-z0-9]{5}$', r'^(.+)-\d+$', r'^(.+)-[a-z0-9]{5}$'):
        m = re.match(pattern, pod)
        if m:
            workload = m.group(1)
            break
    else:
        workload = pod
    if not workload:
        return container
    if not container or container == workload or container in _GENERIC_CONTAINERS:
        return workload
    return f'{workload}/{container}'


def fetch_kubernetes_state(provider, labels, start_time, end_time):
    out = {'terminated': [], 'restarts': {}, 'waiting': [], 'changes': [], 'unavailable': [], 'stuck': [], 'throttled': []}
    if not hasattr(provider, 'query_range_expr'):
        return out

    def query(expr, start=start_time):
        try:
            return provider.query_range_expr(expr, start, end_time) or []
        except Exception as exc:                       # noqa: BLE001
            logger.warning('kube-state-metrics query failed (%s): %s', expr[:80], exc)
            return []

    namespaces = _project_namespaces(query, labels)
    if not namespaces:
        # No namespace of this project: report nothing rather than every
        # namespace of the cluster (kube-system and other teams' projects
        # included), which an empty selector meant (review 2026-11-05).
        return out
    ns = f'namespace=~"{"|".join(namespaces)}"'

    # PromQL range for increase(): the batch window, at least 1 minute so a
    # very short window still spans a scrape interval.
    window = f'{max(1, int((end_time - start_time).total_seconds() // 60))}m'

    _restarts(query, ns, window, out)
    _waiting(query, ns, out)
    _changes(query, ns, start_time - CHANGE_LOOKBACK, out)
    _unavailable(query, ns, out)
    _throttled(query, labels, out)
    for key, limit in _LIMITS.items():
        out[key] = out[key][:limit]
    return out


def _project_namespaces(query, labels):
    selector = ','.join(f'{k}="{_promql_escape(v)}"' for k, v in (labels or {}).items() if v)
    found = set()
    if selector:
        for ts in query(f'count by (namespace) (container_memory_working_set_bytes{{{selector}}})'):
            namespace = (getattr(ts, 'labels', {}) or {}).get('namespace')
            if namespace and _DNS_LABEL.fullmatch(namespace):
                found.add(namespace)
    if not found and (labels or {}).get('environment'):
        found.add(labels['environment'])
    # Namespaces are DNS labels; anything else is not interpolated into PromQL.
    return sorted(n for n in found if _DNS_LABEL.fullmatch(n))


def _promql_escape(value):
    """A PromQL string literal's content: a quote or backslash in a
    project or environment name no longer ends the label matcher."""
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')


def _tags(ts):
    return getattr(ts, 'labels', {}) or {}


def _values(ts):
    return [p.value for p in getattr(ts, 'points', []) if p.value is not None]


def _restarts(query, ns, window, out):
    # `last_terminated_reason` persists for the life of the pod, so a reason
    # is only reported for containers whose restart counter moved in THIS
    # window — otherwise an OOMKill from an earlier incident is attributed to
    # the current one (observed: two fabricated MEMORY_HIGH issues during an
    # unrelated exception scenario).
    reasons = {}
    for ts in query(f'max by (namespace, pod, container, reason) '
                    f'(kube_pod_container_status_last_terminated_reason{{{ns}}} > 0)'):
        t = _tags(ts)
        if t.get('container') and t.get('reason'):
            reasons[workload_name(t.get('pod'), t['container'])] = t['reason']
    for ts in query(f'max by (namespace, pod, container) '
                    f'(increase(kube_pod_container_status_restarts_total{{{ns}}}[{window}]) > 0)'):
        t = _tags(ts)
        values = [v for v in _values(ts) if v]
        if not t.get('container') or not values:
            continue
        name = workload_name(t.get('pod'), t['container'])
        out['restarts'][name] = max(out['restarts'].get(name, 0), int(round(max(values))))
    out['terminated'] = [{'container': name, 'reason': reasons[name]}
                         for name in sorted(out['restarts']) if name in reasons]


def _waiting(query, ns, out):
    seen = set()
    for ts in query(f'max by (namespace, pod, container, reason) '
                    f'(kube_pod_container_status_waiting_reason{{{ns}}} > 0)'):
        t = _tags(ts)
        if t.get('reason') not in _BAD_WAITING or not _values(ts):
            continue
        key = (workload_name(t.get('pod'), t.get('container')), t['reason'])
        if key not in seen:
            seen.add(key)
            out['waiting'].append({'container': key[0], 'reason': key[1]})


def _aware(when):
    # The Prometheus adapter hands back naive UTC timestamps; an ISO string
    # without an offset is read as local time by the browser.
    return when.replace(tzinfo=timezone.utc) if when.tzinfo is None else when


def _steps(ts):
    """[(time, before, after)] for each change of value along the series."""
    steps, previous = [], None
    for point in getattr(ts, 'points', []):
        if point.value is None:
            continue
        if previous is not None and point.value != previous:
            steps.append((_aware(point.timestamp), previous, point.value))
        previous = point.value
    return steps


def _pod_history(query, expr, since, value_of):
    """{workload: [(first seen, last seen, value), ...]}, one entry per pod.

    Kept per pod so that each rollout is described by the pods IT created and
    the pods it replaced. Reading every value the workload had over the
    lookback described a rollback as the bad release again: "rolled out twice
    to v0.10.99", the second time back to v0.10.7 (Online Boutique, rollback
    scenario).
    """
    out = {}
    for ts in query(expr, since):
        t = _tags(ts)
        points = [p for p in getattr(ts, 'points', []) if p.value is not None]
        value = value_of(t, points)
        if value is None or not points:
            continue
        workload = workload_name(t.get('pod'), t.get('container')).split('/')[0]
        out.setdefault(workload, []).append(
            (_aware(points[0].timestamp), _aware(points[-1].timestamp), value))
    return out


def _around(history, when):
    """(value before, value after) a rollout at ``when``: the newest pod alive
    just before it, and the first pod created by it."""
    if not history:
        return None, None
    # Pods created from 30 s before the generation change on are the
    # rollout's (the change is seen at scrape resolution); pods older than
    # that still alive in the two minutes before it are the ones replaced.
    created_from = when - timedelta(seconds=30)
    before = [h for h in history if h[0] < created_from and h[1] >= when - timedelta(minutes=2)]
    after = [h for h in history if h[0] >= created_from]
    old = max(before, key=lambda h: h[0])[2] if before else None
    new = min(after, key=lambda h: h[0])[2] if after else None
    return old, new


def _images(query, ns, since):
    return _pod_history(
        query, f'max by (namespace, pod, container, image) (kube_pod_container_info{{{ns}}})', since,
        lambda t, points: t.get('image') or None)


def _cpu_limits(query, ns, since):
    # Online Boutique, Cloudflare-2019 scenario: a rollout cut the catalogue's
    # CPU limit to 10m. Requests queued before reaching its code, so its own
    # spans stayed fast and the analysis could only guess at "resource
    # throttling" behind a "configuration change".
    return _pod_history(
        query, f'max by (namespace, pod, container) '
               f'(kube_pod_container_resource_limits{{{ns + "," if ns else ""}resource="cpu"}})', since,
        lambda t, points: int(round(points[-1].value * 1000)) if points else None)


def _memory_limits(query, ns, since):
    # A rollout that only cuts a memory limit reads as "a configuration
    # change" without this, and the analysis guessed at a new cache size
    # (Online Boutique B3: the limit had gone from 450Mi to 40Mi).
    return _pod_history(
        query, f'max by (namespace, pod, container) '
               f'(kube_pod_container_resource_limits{{{ns + "," if ns else ""}resource="memory"}})', since,
        lambda t, points: int(points[-1].value) if points else None)


def _mebibytes(value):
    return f'{value / 1048576:.0f}Mi' if value < 1073741824 else f'{value / 1073741824:.1f}Gi'


def _changes(query, ns, since, out):
    images = limits = cpu = None
    for kind, (generation, replicas, label) in _WORKLOAD_KINDS.items():
        scaled_at = {}
        if replicas:
            for ts in query(f'max by (namespace, {label}) ({replicas}{{{ns}}})', since):
                name = _tags(ts).get(label)
                for when, before, after in _steps(ts):
                    scaled_at.setdefault(name, []).append(when)
                    out['changes'].append({
                        'at': when.isoformat(), 'workload': name, 'kind': kind, 'change': 'scaled',
                        'detail': f'replicas {int(before)} -> {int(after)}'})
        for ts in query(f'max by (namespace, {label}) ({generation}{{{ns}}})', since):
            name = _tags(ts).get(label)
            for when, before, after in _steps(ts):
                if after <= before:
                    continue
                # A scale bumps the generation too: already reported as such.
                if any(abs((when - s).total_seconds()) <= 60 for s in scaled_at.get(name, [])):
                    continue
                if images is None:
                    images, limits = _images(query, ns, since), _memory_limits(query, ns, since)
                    cpu = _cpu_limits(query, ns, since)
                out['changes'].append({
                    'at': when.isoformat(), 'workload': name, 'kind': kind, 'change': 'rollout',
                    'detail': _rollout_detail(when, images.get(name), limits.get(name), cpu.get(name))})
    out['changes'].sort(key=lambda c: c['at'], reverse=True)


def _rollout_detail(when, images, limits, cpu=None):
    parts = []
    old_image, new_image = _around(images, when)
    if old_image and new_image and old_image != new_image:
        parts.append(f'image {old_image} -> {new_image}')
    old, new = _around(limits, when)
    if old and new and old != new:
        parts.append(f'memory limit {_mebibytes(old)} -> {_mebibytes(new)}')
    old, new = _around(cpu, when)
    if old and new and old != new:
        parts.append(f'cpu limit {old}m -> {new}m')
    if parts:
        return ', '.join(parts)
    if new_image or old_image:
        return (f'spec changed, image unchanged ({new_image or old_image}): '
                'a configuration or environment change')
    return 'spec changed'


def _unavailable(query, ns, out):
    desired = {}
    for ts in query(f'max by (namespace, deployment) (kube_deployment_spec_replicas{{{ns}}})'):
        values = _values(ts)
        if values:
            desired[_tags(ts).get('deployment')] = int(values[-1])
    updated_now, unready_now = {}, {}
    for ts in query(f'max by (namespace, deployment) (kube_deployment_status_replicas_updated{{{ns}}})'):
        values = _values(ts)
        if values:
            updated_now[_tags(ts).get('deployment')] = int(values[-1])
    for ts in query(f'max by (namespace, deployment) (kube_deployment_status_replicas_unavailable{{{ns}}})'):
        values = _values(ts)
        if values:
            unready_now[_tags(ts).get('deployment')] = int(values[-1])
    for ts in query(f'min by (namespace, deployment) (kube_deployment_status_replicas_available{{{ns}}})'):
        name = _tags(ts).get('deployment')
        values = _values(ts)
        want = desired.get(name)
        if values and want and min(values) < want:
            # The worst moment AND now: a workload back to full strength has
            # recovered, which the worst figure alone hid (rollback scenario).
            out['unavailable'].append({
                'workload': name, 'available': int(min(values)), 'desired': want,
                'now': int(values[-1])})
        available_now = int(values[-1]) if values else 0
        updated = updated_now.get(name)
        # A rollout whose new pods never become ready, while the previous
        # version still serves every replica: no customer is affected yet.
        # Without this the analysis called a crash-looping new pod CRITICAL
        # (Online Boutique, Fastly-2021 scenario). With one replica the new pod
        # already counts as "updated" (1/1), so the not-ready pods are read
        # from replicas_unavailable: the surge pods beyond a full old version.
        not_ready = max(unready_now.get(name, 0), want - updated if want and updated is not None else 0)
        if want and not_ready > 0 and available_now >= want:
            out['stuck'].append({'workload': name, 'not_ready': not_ready, 'available': available_now, 'desired': want})


def _throttled(query, labels, out):
    """Services the kernel paused for exceeding their CPU limit, from cAdvisor.

    A throttled service answers slowly while its own spans and its CPU usage
    look modest: the time is lost waiting for CPU, before and between its
    work. These series are cAdvisor's, so they carry the project's labels.
    """
    # No container!="" filter: under the Docker runtime cAdvisor reports these
    # per pod only, without a container label. Where both pod and container
    # series exist, each is counted in both sums and the ratio is unchanged.
    selector = ','.join(f'{k}="{_promql_escape(v)}"' for k, v in (labels or {}).items() if v)
    expr = (f'100 * sum by (service_name) (rate(container_cpu_cfs_throttled_periods_total{{{selector}}}[5m])) '
            f'/ sum by (service_name) (rate(container_cpu_cfs_periods_total{{{selector}}}[5m]))')
    for ts in query(expr):
        name = _tags(ts).get('service_name')
        values = [v for v in _values(ts) if v == v]    # drop NaN (no periods yet)
        if name and values and max(values) >= THROTTLED_PERCENT:
            out['throttled'].append({'service': name, 'percent': round(max(values))})
    out['throttled'].sort(key=lambda t: t['percent'], reverse=True)
