"""One ordering for "which issue leads": the analysis headline, the post-mortem
draft and incident notifications all take the first issue of a batch.

Most severe first, then most confident, then the AI's own order (issues are
created in the order the AI listed them, root cause first). Issue's default
ordering is newest first and severity sorts alphabetically in SQL (INFO before
WARNING), so neither can be used for this.
"""

SEVERITY_RANK = {'CRITICAL': 0, 'WARNING': 1, 'INFO': 2}
CONFIDENCE_RANK = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}


def root_cause_first(issues):
    return sorted(
        issues,
        key=lambda i: (
            SEVERITY_RANK.get((i.severity or '').upper(), 3),
            CONFIDENCE_RANK.get((i.confidence or '').upper(), 3),
            i.created_at, i.pk,
        ),
    )
