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

from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce, Length
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
        # The team's root cause (given on resolve) counts as well as the AI's.
        .annotate(
            _rc_len=Coalesce(Length('root_cause'), 0),
            _team_len=Coalesce(Length('resolution_root_cause'), 0),
            # Root causes the team confirmed or corrected come first.
            _confirmed=Case(When(Q(_team_len__gte=MIN_ROOT_CAUSE_LENGTH), then=Value(1)),
                            default=Value(0), output_field=IntegerField()),
        )
        .filter(Q(_rc_len__gte=MIN_ROOT_CAUSE_LENGTH) | Q(_team_len__gte=MIN_ROOT_CAUSE_LENGTH))
    )
    order = ('-_confirmed', '-resolved_at')

    exact = list(
        base_qs.filter(environment=environment).order_by(*order)[:limit]
    )

    if len(exact) >= limit:
        return [(issue, 'exact') for issue in exact]

    remaining = limit - len(exact)
    exact_ids = [issue.id for issue in exact]
    broader = list(
        base_qs.exclude(environment=environment)
        .exclude(id__in=exact_ids)
        .order_by(*order)[:remaining]
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
        ai_root_cause = (issue.root_cause or '').strip()
        team_root_cause = (issue.resolution_root_cause or '').strip()
        fix = issue.effective_fix[:150] or 'none recorded'
        if len(team_root_cause) >= MIN_ROOT_CAUSE_LENGTH:
            if team_root_cause == ai_root_cause:
                cause = f'  Root cause (confirmed by the team): {team_root_cause[:200]}'
            else:
                # Show the correction: the AI learns what it got wrong.
                cause = (f'  Root cause (corrected by the team): {team_root_cause[:200]}\n'
                         f'  The AI had said: {ai_root_cause[:150] or "nothing"}')
        else:
            cause = f'  Root cause (AI, not confirmed): {ai_root_cause[:200]}'
        lines.append(
            f'- [{date}] {issue.issue_type} on {component}{env_tag}\n'
            f'{cause}\n'
            f'  Fix: {fix}'
        )
    return '\n'.join(lines)
