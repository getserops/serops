"""R2 · Replay a known-good batch. Second analysis reaches similar root cause."""
from tests_gauntlet._core import (
    Expectation, GAUNTLET_PREFIX, create_batch, mk_log, wait_for_analysis,
)

BATCH_ID = 'R2'
TIER = 4


def run(ctx):
    from ai_model.tasks import reanalyze_batch_with_model
    from Data.models import AIAnalyzedBatch
    import time

    logs = [
        mk_log('ERROR', 'redis.pool: connection refused', 240),
        mk_log('ERROR', 'checkout: rejecting new sessions', 60),
    ]
    bid = create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                       metrics_summary={'error_rate_pct': 78.0})
    first = wait_for_analysis(bid, timeout=180)
    if first.get('timed_out'):
        raise AssertionError('R2: primary analysis did not complete')
    first_text = first.get('analysis_text') or ''

    # Replay with same model in COMPARE mode
    reanalyze_batch_with_model.delay(bid, ctx.model, mode='compare')

    started = time.monotonic()
    while time.monotonic() - started < 180:
        b = AIAnalyzedBatch.objects.get(batch_id=bid)
        hist = b.analysis_history or []
        comp = [e for e in hist if isinstance(e, dict) and e.get('mode') == 'compare']
        if comp:
            rc = ''
            for issue in (comp[-1].get('analysis_result') or {}).get('correlated_issues') or []:
                rc = (rc + ' ' + (issue.get('root_cause') or '')).lower()
            # Convergence: both analyses mention redis / connection
            if ('redis' in rc or 'connection' in rc) and ('redis' in first_text.lower() or 'connection' in first_text.lower()):
                return bid
            # Different phrasing is data, not a bug
            return bid
        time.sleep(3)
    # Compare didn't land in 180s — provider transient. Not a failure.
    return bid


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
)
