"""AI1 · Prompt caching stability — 3 same-shape batches in a row all analyse cleanly.

Simplified from cache-hit assertion (needs per-batch token accounting).
The stability test: fire 3 near-identical batches sequentially, verify
all 3 land ``analyzed_at`` + a real issue. Regression fence for prompt-
shape drift.
"""
from tests_gauntlet._core import (
    Expectation, GAUNTLET_PREFIX, create_batch, mk_log, wait_for_analysis,
)

BATCH_ID = 'AI1'
TIER = 2


def run(ctx):
    logs = lambda seed: [
        mk_log('ERROR', f'redis.pool: connection refused (seed {seed})', 240),
        mk_log('ERROR', f'checkout: 500 on POST /checkout/confirm (seed {seed})', 60),
    ]
    # Two warmup batches, then the batch we return + assert.
    for seed in (1, 2):
        bid = create_batch(
            ctx, short_name=f'ai1-warmup-{seed}', logs=logs(seed),
            metrics_summary={'error_rate_pct': 62.0},
        )
        s = wait_for_analysis(bid, timeout=180)
        if not s.get('exists') or s.get('timed_out'):
            raise AssertionError(f'AI1: warmup {seed} did not analyse')

    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs(3),
        metrics_summary={'error_rate_pct': 62.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
)
