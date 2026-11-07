"""
Past-Incident Memory — inject resolved-issue root causes into AI prompts.

Lookups are scoped strictly by `organisation` (multi-tenancy) and filter out
junk root causes (`MIN_ROOT_CAUSE_LENGTH`).

With a ``query_text`` (the batch's log digest, ``query_text_for_batch``)
memories are the resolved issues MOST SIMILAR to the current batch — via
the org's embedding provider or local lexical similarity, see
``Data.embeddings.SimilarityQuery`` — with same-environment, team-confirmed
and recency as tiebreaks, plus at most ``RECENCY_SLICE`` recent issue when
fewer similar ones exist. External review (v1.2.13): memories used to be
just the most recent resolved issues, whatever they were about.

Without a query (nothing to compare against) the two-tier recency match
applies: same-environment memories first, then other environments of the
same project — tagged honestly in the formatter so the AI does not
over-trust them.

Public interface:
    find_past_memories(project, environment, organisation, settings=None,
                       query_text=None)
        -> list[tuple[Issue, str]]   # str is 'exact' or 'broader'
    query_text_for_batch(batch) -> str
    format_memories_for_prompt(memory_tuples) -> str

The (Issue, tier) return type is the contract — implementation is swappable
(e.g., pgvector cosine similarity) without touching callers.
"""

import re
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

# With a query, how many non-matching recent issues may still fill empty
# slots. One keeps "what changed recently" context without letting
# unrelated incidents crowd the prompt.
RECENCY_SLICE = 1

# Upper bound on candidates scored per query (newest first). Scoring is
# local and cheap, but a busy project's 90-day window is unbounded.
_MAX_CANDIDATES = 500

# Batch digest limits: unique messages, characters per message.
_QUERY_MAX_LINES = 40
_QUERY_LINE_CHARS = 300
_HIGH_SIGNAL_LEVELS = ('ERROR', 'WARN', 'CRITICAL', 'FATAL', 'ALERT',
                       'EMERG', 'SEVERE', 'PANIC')


def find_past_memories(project, environment, organisation, settings=None,
                       query_text=None):
    """Return resolved-issue memories for AI prompt injection.

    Args:
        project: Project instance (required)
        environment: environment string, e.g. "production" (may be empty)
        organisation: Organisations instance (required for multi-tenancy isolation)
        settings: optional IssueSettings instance; loaded from DB when omitted
        query_text: what the current batch is about (``query_text_for_batch``);
            when given, memories are ranked by similarity to it

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

    if query_text and query_text.strip():
        return _most_similar(base_qs, environment, organisation, limit, query_text)

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


def _most_similar(base_qs, environment, organisation, limit, query_text):
    """Rank the window's resolved issues by similarity to ``query_text``."""
    from Data.embeddings import SimilarityQuery, embed_text

    matcher = SimilarityQuery(query_text, embed_text(query_text, organisation=organisation))
    candidates = list(base_qs.order_by('-resolved_at')[:_MAX_CANDIDATES])

    matches, others = [], []
    for issue in candidates:
        _sim, relevance = matcher.score(issue)
        tier = 'exact' if issue.environment == environment else 'broader'
        (matches if relevance >= 0 else others).append((relevance, issue, tier))

    # Similarity first; ties (rounded) go to same environment, then
    # team-confirmed root causes, then the most recent.
    matches.sort(key=lambda t: (round(t[0], 3), t[2] == 'exact',
                                t[1]._confirmed, t[1].resolved_at),
                 reverse=True)
    picked = [(issue, tier) for _rel, issue, tier in matches[:limit]]

    # ``others`` is already newest-first (candidate order).
    others.sort(key=lambda t: (t[2] == 'exact', t[1]._confirmed), reverse=True)
    room = min(limit - len(picked), RECENCY_SLICE)
    picked += [(issue, tier) for _rel, issue, tier in others[:max(0, room)]]
    return picked


def query_text_for_batch(batch):
    """Digest of what a batch is about, for memory similarity: the
    triggering alert, unique high-signal log messages (numbers folded so
    repeats collapse), and failed CI/CD jobs. Empty string when the batch
    holds nothing usable."""
    data = getattr(batch, 'data', None)
    if not isinstance(data, dict):
        return ''

    lines = []
    alert = data.get('triggering_alert')
    if isinstance(alert, dict):
        alert_text = ' '.join(
            str(alert.get(k) or '') for k in ('title', 'name', 'alertname', 'summary',
                                              'description', 'message')
        ).strip()
        if alert_text:
            lines.append(alert_text[:_QUERY_LINE_CHARS])

    high, other, seen = [], [], set()
    for log in data.get('logs') or []:
        if not isinstance(log, dict):
            continue
        src = log.get('_source', log)
        if not isinstance(src, dict):
            continue
        message = str(src.get('message') or '').strip()[:_QUERY_LINE_CHARS]
        if not message:
            continue
        key = re.sub(r'\d+', '#', message)
        if key in seen:
            continue
        seen.add(key)
        service = src.get('service')
        component = (service.get('name') if isinstance(service, dict) else None) \
            or src.get('service_name') or (service if isinstance(service, str) else None) \
            or src.get('component') or ''
        line = f'{component}: {message}' if component else message
        level = str(src.get('log_level') or src.get('level') or '').upper()
        (high if level.startswith(_HIGH_SIGNAL_LEVELS) else other).append(line)
    lines += (high or other)[:_QUERY_MAX_LINES]

    for job in data.get('cicd_logs') or []:
        if isinstance(job, dict) and job.get('status') == 'failed':
            lines.append(f"CI job {job.get('job_name', '')} failed: "
                         f"{str(job.get('trace_errors') or '')[:_QUERY_LINE_CHARS]}")
    return '\n'.join(lines)


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
