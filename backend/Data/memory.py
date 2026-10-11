"""
Past-Incident Memory — inject resolved-issue root causes into AI prompts.

Lookups are scoped strictly by `organisation` (multi-tenancy) and filter out
junk root causes (`MIN_ROOT_CAUSE_LENGTH`). The two-tier match prefers
same-environment memories first, falls back to other environments of the
same project so cross-env recurrences are still surfaced — tagged honestly
in the formatter so the AI does not over-trust them.

Public interface:
    find_past_memories(project, environment, organisation, settings=None)
        -> list[tuple[Issue, str]]   # str is 'exact' or 'broader'
    format_memories_for_prompt(memory_tuples) -> str

The (Issue, tier) return type is the contract — implementation is swappable
(e.g., pgvector cosine similarity) without touching callers.
"""

from datetime import timedelta

from django.db.models.functions import Length
from django.utils import timezone


# Resolved issues with a root cause shorter than this are filtered out.
# Avoids leaking junk like "fixed", "n/a", "manual" into AI prompts.
MIN_ROOT_CAUSE_LENGTH = 30

# Hard defaults used when no IssueSettings record exists for the org.
_DEFAULT_WINDOW_DAYS = 90
_DEFAULT_MAX_ITEMS = 3


def find_past_memories(project, environment, organisation, settings=None):
    """Return resolved-issue memories for AI prompt injection.

    Args:
        project: Project instance (required)
        environment: environment string, e.g. "production" (may be empty)
        organisation: Organisations instance (required for multi-tenancy isolation)
        settings: optional IssueSettings instance; loaded from DB when omitted

    Returns:
        list of (Issue, tier) tuples where tier is "exact" (same environment)
        or "broader" (same project, different environment). Empty list when
        memory is disabled, no project/organisation is supplied, or no
        resolved issues qualify.
    """
    if not project or not organisation:
        return []

    if settings is None:
        from org_settings.models import IssueSettings
        settings = IssueSettings.objects.filter(organisation=organisation).first()

    if settings is not None and not settings.memory_enabled:
        return []

    window_days = settings.memory_window_days if settings else _DEFAULT_WINDOW_DAYS
    limit = settings.memory_max_items if settings else _DEFAULT_MAX_ITEMS

    if limit <= 0:
        return []

    # Late import — Issue lives in this app and importing at module load
    # would risk circular imports during Django app registry setup.
    from Data.models import Issue

    cutoff = timezone.now() - timedelta(days=window_days)

    base_qs = (
        Issue.objects
        .filter(
            organisation=organisation,
            project=project,
            status='RESOLVED',
            resolved_at__gte=cutoff,
        )
        .exclude(root_cause__isnull=True)
        .annotate(_rc_len=Length('root_cause'))
        .filter(_rc_len__gte=MIN_ROOT_CAUSE_LENGTH)
    )

    exact = list(
        base_qs.filter(environment=environment).order_by('-resolved_at')[:limit]
    )

    if len(exact) >= limit:
        return [(issue, 'exact') for issue in exact]

    remaining = limit - len(exact)
    exact_ids = [issue.id for issue in exact]
    broader = list(
        base_qs.exclude(environment=environment)
        .exclude(id__in=exact_ids)
        .order_by('-resolved_at')[:remaining]
    )

    return (
        [(issue, 'exact') for issue in exact]
        + [(issue, 'broader') for issue in broader]
    )


def format_memories_for_prompt(memory_tuples):
    """Render memory tuples as a compact prompt section.

    Cross-environment memories are tagged so the AI treats them as weaker
    signals. Returns an empty string when the list is empty so the prompt
    builder can omit the section header cleanly.
    """
    if not memory_tuples:
        return ''

    lines = [
        'Past Incident Memory (resolved issues from this project — '
        'use as diagnostic hints, NOT as ground truth for the current batch):'
    ]
    for issue, tier in memory_tuples:
        date = issue.resolved_at.strftime('%Y-%m-%d') if issue.resolved_at else 'unknown'
        env_tag = '' if tier == 'exact' else f' [different env: {issue.environment or "unknown"}]'
        component = issue.component or 'unknown component'
        root_cause = (issue.root_cause or '').strip()[:200]
        recommendation = (issue.recommendation or '').strip()[:150] or 'none recorded'
        lines.append(
            f'- [{date}] {issue.issue_type} on {component}{env_tag}\n'
            f'  Root cause: {root_cause}\n'
            f'  Fix: {recommendation}'
        )
    return '\n'.join(lines)
