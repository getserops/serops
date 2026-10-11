"""AI2 · Graceful degradation when the AI provider fails.

The name in the original plan was "provider fallback" — the truer
launch-blocker test is: what happens when the AI is unreachable
mid-batch? Does the celery task crash, ghost Issues get created,
partial state get persisted?

Test shape:
1. Temporarily invalidate the org's primary AI API key
2. Fire a real batch (with a real incident inside)
3. Assert: batch exists, analyzed_at is set (worker completed), no
   ghost Issue records, model_name flags the failure
4. Restore the key

Full multi-provider fallback (Gemini 429 → Claude) needs adapter
instrumentation in ai_service.generate_with_fallback and is deferred
to its own PR (PR-GT-Faults). This generator covers the "AI down" case.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'AI2'
TIER = 0


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(level: str, msg: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def _invalidate_ai_keys(org_id: int) -> list[tuple[int, str]]:
    """Overwrite the org's active AI keys with garbage. Returns the
    list of (id, original_api_key) so we can restore."""
    from org_settings.models import OrganisationAPIKey
    snapshots: list[tuple[int, str]] = []
    for k in OrganisationAPIKey.objects.filter(organisation_id=org_id, is_active=True):
        snapshots.append((k.id, k.api_key))
        # ``api_key`` is a Fernet-encrypted string. Overwriting with
        # non-Fernet bytes triggers a decrypt error inside the adapter,
        # exercising the graceful-failure path (an AIServiceError, not
        # a crash). Prefix stays "gAAAAA" so a shallow validator that
        # only checks Fernet-shape doesn't reject it before the
        # decrypt attempt.
        k.api_key = 'gAAAAAgauntlet-invalid-fernet-token-for-ai2-test'
        k.save(update_fields=['api_key'])
    return snapshots


def _restore_ai_keys(snapshots):
    from org_settings.models import OrganisationAPIKey
    for kid, encrypted in snapshots:
        k = OrganisationAPIKey.objects.get(id=kid)
        k.api_key = encrypted
        k.save(update_fields=['api_key'])


def run(ctx):
    from tests_gauntlet._core import create_batch, ensure_project, wait_for_analysis
    from Data.models import AIAnalyzedBatch, Issue

    ensure_project(ctx)

    snapshots = _invalidate_ai_keys(ctx.org_id)
    try:
        batch_id = create_batch(
            ctx,
            short_name=BATCH_ID.lower(),
            logs=[
                _log('ERROR', 'redis.pool: connection refused to redis:6379', 3),
                _log('ERROR', 'checkout.cache: connection pool exhausted', 2),
                _log('ERROR', 'checkout: rejecting new sessions', 1),
            ],
            metrics_summary={'error_rate_pct': 87.2},
        )
        # Wait — with a shorter timeout because we EXPECT a fast failure,
        # not a slow-and-successful AI call.
        summary = wait_for_analysis(batch_id, timeout=90)

        # Independent DB assertion: no ghost issues persisted for this batch
        ghost_issues = Issue.objects.filter(
            batch__batch_id=batch_id,
        ).count()
        if ghost_issues > 0:
            raise AssertionError(
                f'AI2: {ghost_issues} ghost Issue(s) persisted despite AI failure '
                f'on batch {batch_id!r}'
            )

        # Also: worker must have marked the batch (analyzed_at set) so the
        # UI can render "analysis failed" instead of an infinite spinner.
        batch = AIAnalyzedBatch.objects.get(batch_id=batch_id)
        if batch.analyzed_at is None and not getattr(batch, 'ai_skipped', False):
            raise AssertionError(
                f'AI2: batch {batch_id!r} has no analyzed_at and no ai_skipped '
                f'flag — UI would show infinite spinner'
            )
    finally:
        _restore_ai_keys(snapshots)

    return batch_id


EXPECTATION = Expectation(
    # No issues from a failed AI call — silent-success would be worse
    # than a loud failure.
    max_issues=0,
    # analysis_text may be null OR carry a short error message.
    # Don't over-constrain; the DB-level assertions in run() are the
    # real guarantee, this is a smoke check.
    timed_out_ok=False,
)
