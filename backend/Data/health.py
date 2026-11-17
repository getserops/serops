"""
One health formula for the Overview dashboard.

System Health (``/analytics/health/``), the Service Health Map
(``/analytics/service-health/``) and Top Failing Services
(``/analytics/services/``) all score with :func:`health_score` and label
with the same thresholds, so a service the map shows as healthy can't
top the failing list and a red map tile can't sit under a green
System Health for the same slice.

Formula (inputs are the issues that are **open now**; muted and resolved
issues don't count, however old or new they are)::

    penalty = 20 x open CRITICAL + 6 x open WARNING + 2 x any other open issue
    bonus   = min(10, 2 x issues resolved in the last 24 hours)   (only when something is open)
    score   = clamp(100 - penalty + bonus, 0, 100)                (100 when nothing is open)

Thresholds::

    Healthy   score >= 85
    Degraded  60 <= score < 85
    Critical  score < 60

So one open warning is 94 % (Healthy), one open critical 80 % (Degraded),
three open criticals 40 % (Critical).

Documented for users in docs/src/user-guide/dashboard.md ("How health is
scored"). Change both together.
"""
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

HEALTHY_MIN = 85
DEGRADED_MIN = 60

PENALTY_CRITICAL = 20
PENALTY_WARNING = 6
PENALTY_OTHER = 2
RECOVERY_BONUS_PER_RESOLVED = 2
RECOVERY_BONUS_MAX = 10
RECOVERY_WINDOW = timedelta(hours=24)


def health_score(critical_open, warning_open, other_open=0, resolved_recent=0):
    """Return ``(score, status)`` for the given open-issue counts.

    ``status`` is ``'Healthy'``, ``'Degraded'`` or ``'Critical'``; see the
    module docstring for the formula and thresholds.
    """
    if critical_open + warning_open + other_open == 0:
        score = 100
    else:
        penalty = (critical_open * PENALTY_CRITICAL
                   + warning_open * PENALTY_WARNING
                   + other_open * PENALTY_OTHER)
        bonus = min(RECOVERY_BONUS_MAX, resolved_recent * RECOVERY_BONUS_PER_RESOLVED)
        score = round(max(0, min(100, 100 - penalty + bonus)))
    return score, health_status(score)


def health_status(score):
    if score >= HEALTHY_MIN:
        return 'Healthy'
    if score >= DEGRADED_MIN:
        return 'Degraded'
    return 'Critical'


def _counts():
    since = timezone.now() - RECOVERY_WINDOW
    return dict(
        open_count=Count('id', filter=Q(status='OPEN')),
        critical=Count('id', filter=Q(status='OPEN', severity='CRITICAL')),
        warning=Count('id', filter=Q(status='OPEN', severity='WARNING')),
        resolved_recent=Count('id', filter=Q(status='RESOLVED', resolved_at__gte=since)),
    )


def _scored(row):
    critical, warning = row['critical'], row['warning']
    other = row['open_count'] - critical - warning
    score, status = health_score(critical, warning, other, row['resolved_recent'])
    return {
        'open_issues': row['open_count'],
        'critical_issues': critical,
        'warning_issues': warning,
        'resolved_last_24h': row['resolved_recent'],
        'health_score': score,
        'status': status,
    }


def overall_health(issues):
    """Score a whole (already org/env/cluster-filtered) Issue queryset."""
    return _scored(issues.aggregate(**_counts()))


def health_by_component(issues):
    """Score each ``(project_id, component)`` of an Issue queryset.

    Returns ``{(project_id, component_lower): {..., 'component': name}}``.
    An issue's project is its own, else its batch's. Issues without a
    component are left out: they belong to no service.
    """
    rows = (issues.exclude(component='')
            .annotate(pid=Coalesce('project_id', 'batch__project_id'), comp=Lower('component'))
            .values('pid', 'comp')
            .annotate(**_counts())
            .order_by())
    # Keep the component's own spelling for display.
    spelled = dict(issues.exclude(component='')
                   .annotate(comp=Lower('component'))
                   .values_list('comp', 'component').distinct().order_by())
    result = {}
    for row in rows:
        scored = _scored(row)
        scored['component'] = spelled.get(row['comp'], row['comp'])
        scored['project_id'] = row['pid']
        result[(row['pid'], row['comp'])] = scored
    return result
