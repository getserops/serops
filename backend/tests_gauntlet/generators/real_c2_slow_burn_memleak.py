"""C2 · Slow-burn memory leak over 6 h; OOM at the end. Single batch snapshot."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'C2'
TIER = 3


def run(ctx):
    # 6h simulated in 300s log spread; every "step" is 40s apart
    steps = [
        (240, 'INFO',  'heap.usage: 62% (+3pp since last)'),
        (200, 'WARN',  'heap.usage: 74% (+12pp) — trend concerning'),
        (160, 'WARN',  'heap.usage: 86% · full-gc 620ms'),
        (120, 'ERROR', 'heap.usage: 96% · full-gc 3400ms · SLOs breached'),
        (60,  'ERROR', 'OOMKilled: checkout pod 2847 (leaked 190MB/hr)'),
        (10,  'ERROR', 'checkout: 500 on POST /checkout/confirm (post-restart cold cache)'),
    ]
    logs = [mk_log(lvl, msg, sec) for sec, lvl, msg in steps]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'memory': {'usage_percent': {'avg': 87.0}}, 'error_rate_pct': 12.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['memory', 'leak', 'heap', 'oom'],
)
