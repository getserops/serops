"""Post-mortem draft generator — Item #28.

Produces a starter post-mortem markdown for an analyzed batch,
seeded with:

* The batch's top issues (root cause, recommendation, severity).
* Recent code changes in the window (deploy context).
* Similar past resolved incidents (via Item #27) — precedent + how
  the team fixed them before.

The AI writes placeholder timeline entries + explicit
"[FILL IN: ...]" prompts the SRE completes. It's a draft — not a
finished document.

Design:

* Uses the same ``ai_service`` provider path as batch analysis, so
  the org's existing AI budget + rate-limits apply.
* Falls back to a **template-based** post-mortem when the AI call
  fails (network / rate limit / no API key). The template renders
  the same sections with the raw data — still useful, just not
  polished prose.

Security:

* Log / trace attributes are already redacted when stored on the
  batch (see ``Utils.data_redaction`` in the batch pipeline). We
  pass the same redacted content through — no additional egress
  risk beyond what the org has already accepted for normal batch
  analysis.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_postmortem_draft(batch) -> str:
    """
    Return a markdown post-mortem draft for ``batch``.

    Never raises — falls back to the template on any AI failure.
    """
    context = _gather_context(batch)
    prompt = _build_prompt(context)

    # Try the AI service first. Any failure → template fallback.
    try:
        markdown = _ai_generate(prompt, batch)
        if markdown and len(markdown.strip()) > 100:
            return markdown
    except Exception as exc:
        logger.warning('postmortem AI generation failed for batch %s: %s',
                       getattr(batch, 'batch_id', '?'), exc)

    return _template_postmortem(context)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def _gather_context(batch) -> dict:
    """Collect the data the AI + template both need."""
    ctx = {
        'batch_id': getattr(batch, 'batch_id', ''),
        'timestamp': getattr(batch, 'timestamp', None),
        'environment': getattr(batch, 'environment', '') or 'unknown',
        'project_name': (
            batch.project.name if getattr(batch, 'project', None) else 'unknown'
        ),
        'top_issues': [],
        'code_changes': [],
        'similar_past': [],
    }

    try:
        issues = list(
            batch.issues.order_by('severity', '-created_at')[:3]
        )
        ctx['top_issues'] = [
            {
                'severity': i.severity,
                'issue_type': i.issue_type,
                'component': i.component,
                'description': (i.description or '')[:300],
                'root_cause': (i.root_cause or '')[:500],
                'recommendation': (i.recommendation or '')[:500],
            }
            for i in issues
        ]
    except Exception:
        pass

    try:
        code_changes = (batch.data or {}).get('code_changes') or []
        ctx['code_changes'] = [
            {
                'sha': str(c.get('sha', ''))[:8],
                'author': c.get('author', ''),
                'message': (c.get('message', '') or '')[:120],
                'timestamp': c.get('timestamp'),
            }
            for c in code_changes[:5]
        ]
    except Exception:
        pass

    # Similar past incidents — pull from the first top issue's find_similar.
    try:
        if issues and issues[0].embedding:
            similar = issues[0].find_similar(top_k=3)
            ctx['similar_past'] = [
                {
                    'similarity': m['similarity'],
                    'component': m['issue'].component,
                    'issue_type': m['issue'].issue_type,
                    'root_cause': (m['issue'].root_cause or '')[:200],
                    'recommendation': (m['issue'].recommendation or '')[:200],
                    'resolved_at': m['issue'].resolved_at.isoformat() if m['issue'].resolved_at else None,
                }
                for m in similar
            ]
    except Exception:
        pass

    return ctx


# ---------------------------------------------------------------------------
# AI path
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are an experienced SRE writing a post-mortem draft.

Return a Markdown document with these sections:
1. `# Post-mortem: <short title>`
2. `## Summary` — 2-3 sentence outage description in plain English.
3. `## Impact` — [FILL IN: users affected, duration, revenue if known].
4. `## Timeline` — starter entries from the data provided; add
   `- [FILL IN: ... ]` placeholders for what the SRE needs to
   backfill (detection time, first responder, mitigation steps).
5. `## Root cause` — from the AI analysis. Add
   `[FILL IN: verification]` after each hypothesis.
6. `## Contributing factors` — enumerate; add [FILL IN: ...] for
   organisational / process factors.
7. `## What went well` — bullets, prompted with placeholders.
8. `## What to improve` — bullets, drawn from recommendations + [FILL IN].
9. `## Action items` — table `Action | Owner | Due | Priority`
   with the AI's recommendations as rows and [FILL IN: owner/date]
   placeholders.
10. `## Precedent` — if similar past incidents are provided, list
    them with links to the recommendations.

Rules:
- Use only the data provided. Do NOT invent stack traces / SHAs / user counts.
- Wrap every SRE decision in `[FILL IN: ...]` markers.
- Keep it under 800 words — SREs need a starting point, not a novel.
- Output only the Markdown. No preamble, no code fences around the whole doc.
"""


def _build_prompt(context: dict) -> str:
    """Format the context as user prompt for the AI."""
    parts = [
        f"Batch ID: {context['batch_id']}",
        f"Project: {context['project_name']}",
        f"Environment: {context['environment']}",
        f"Occurred: {context['timestamp']}",
        "",
        "## Top issues:",
    ]
    if not context['top_issues']:
        parts.append("(no issues recorded — analysis produced no findings)")
    for issue in context['top_issues']:
        parts.append(
            f"- [{issue['severity']}] {issue['issue_type']} in "
            f"{issue['component'] or '(no component)'}"
        )
        if issue['root_cause']:
            parts.append(f"  Root cause: {issue['root_cause']}")
        if issue['recommendation']:
            parts.append(f"  Recommendation: {issue['recommendation']}")

    if context['code_changes']:
        parts.append("")
        parts.append("## Deploys in the window:")
        for c in context['code_changes']:
            parts.append(
                f"- {c['sha']} — {c['author']} — {c['message']}"
            )

    if context['similar_past']:
        parts.append("")
        parts.append("## Similar past resolved incidents (for precedent):")
        for s in context['similar_past']:
            parts.append(
                f"- [{int(s['similarity'] * 100)}% match] "
                f"{s['issue_type']} in {s['component'] or '?'}: "
                f"root cause: {s['root_cause']}"
            )
            if s['recommendation']:
                parts.append(f"  Then-recommendation: {s['recommendation']}")

    parts.append("")
    parts.append("Now write the post-mortem draft.")
    return "\n".join(parts)


def _ai_generate(prompt: str, batch) -> str:
    """
    Route through the org's configured AI provider via
    ``ai_service.generate_for_organisation``.

    Returns markdown string on success. Returns empty string on any
    non-exceptional failure (rate limit, empty response, org has no
    AI provider configured); the caller falls back to the template.
    """
    from ai_model.ai_service import generate_for_organisation
    from ai_model.exceptions import NoAIProviderConfigured

    organisation = None
    if getattr(batch, 'project', None) is not None:
        organisation = batch.project.organisation
    if organisation is None:
        return ''

    try:
        response, provider_used, error, _tin, _tout = generate_for_organisation(
            prompt=prompt,
            organisation=organisation,
            system_prefix=_SYSTEM_PROMPT,
        )
    except NoAIProviderConfigured:
        return ''

    if error or not response:
        return ''
    return str(response).strip()


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------


def _template_postmortem(context: dict) -> str:
    """
    Deterministic template renderer — used when the AI is unavailable.

    Produces a valid post-mortem draft with all sections + [FILL IN]
    prompts. Not as polished as the AI output but strictly better
    than a 500 error.
    """
    project = context['project_name']
    env = context['environment']
    when = _fmt_time(context['timestamp'])
    top = context['top_issues']
    changes = context['code_changes']
    similar = context['similar_past']

    title = _title_from_top_issue(top, project, env)

    lines: List[str] = []
    lines.append(f'# Post-mortem: {title}')
    lines.append('')
    lines.append('## Summary')
    lines.append(f'On {when}, an incident affected `{project}` in `{env}`.')
    if top:
        lines.append(
            f"SerOps identified {len(top)} issue(s), the most severe being "
            f"a {top[0]['severity']} `{top[0]['issue_type']}`."
        )
    lines.append('')
    lines.append('## Impact')
    lines.append('- Users affected: [FILL IN]')
    lines.append('- Duration: [FILL IN]')
    lines.append('- Revenue / SLO impact: [FILL IN]')
    lines.append('')
    lines.append('## Timeline')
    lines.append(f'- **{when}** — SerOps batch `{context["batch_id"]}` created.')
    lines.append('- [FILL IN: when detected] — [FILL IN: who / what alerted]')
    lines.append('- [FILL IN: when mitigation started] — [FILL IN: what was done]')
    lines.append('- [FILL IN: when resolved] — [FILL IN: verification]')
    lines.append('')
    lines.append('## Root cause')
    if top and top[0]['root_cause']:
        lines.append(top[0]['root_cause'])
        lines.append('')
        lines.append('_[FILL IN: verify against logs / traces]_')
    else:
        lines.append('_[FILL IN: root cause hypothesis]_')
    lines.append('')
    lines.append('## Contributing factors')
    for issue in top[1:]:
        lines.append(
            f'- {issue["severity"]} `{issue["issue_type"]}` in '
            f'{issue["component"] or "(no component)"}'
        )
    lines.append('- [FILL IN: organisational / process factors]')
    lines.append('')
    lines.append('## What went well')
    lines.append('- SerOps produced an AI RCA within minutes.')
    lines.append('- [FILL IN: other positives]')
    lines.append('')
    lines.append('## What to improve')
    if top and top[0]['recommendation']:
        lines.append(f'- {top[0]["recommendation"]}')
    lines.append('- [FILL IN: additional improvements]')
    lines.append('')
    lines.append('## Action items')
    lines.append('')
    lines.append('| Action | Owner | Due | Priority |')
    lines.append('|---|---|---|---|')
    for issue in top:
        if issue['recommendation']:
            lines.append(
                f'| {issue["recommendation"][:80]} | [FILL IN] | [FILL IN] | '
                f'{issue["severity"]} |'
            )
    lines.append('| [FILL IN] | [FILL IN] | [FILL IN] | [FILL IN] |')

    if changes:
        lines.append('')
        lines.append('## Deploys in the incident window')
        for c in changes:
            lines.append(
                f'- `{c["sha"]}` — {c["author"]} — {c["message"]}'
            )

    if similar:
        lines.append('')
        lines.append('## Precedent — similar past incidents')
        for s in similar:
            pct = int(s['similarity'] * 100)
            lines.append(
                f'- **{pct}% match** — `{s["issue_type"]}` in '
                f'`{s["component"] or "?"}` (resolved {_fmt_time(s["resolved_at"])})'
            )
            if s['recommendation']:
                lines.append(f'  Then-recommendation: {s["recommendation"]}')

    return '\n'.join(lines) + '\n'


def _title_from_top_issue(top: list, project: str, env: str) -> str:
    if not top:
        return f'{project} incident ({env})'
    issue = top[0]
    return (
        f'{issue["issue_type"].replace("_", " ").title()} in '
        f'{issue["component"] or project} ({env})'
    )


def _fmt_time(t) -> str:
    if t is None:
        return '[FILL IN: time]'
    if isinstance(t, datetime):
        return t.strftime('%Y-%m-%d %H:%M UTC')
    return str(t)
