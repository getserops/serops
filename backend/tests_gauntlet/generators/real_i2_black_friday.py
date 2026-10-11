"""I2 · Legit spike — 10x traffic, everything degraded, nothing broken. AI must not blame code."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'I2'
TIER = 3


def run(ctx):
    logs = [
        mk_log('INFO',  'traffic: 47000 req/s (baseline 4700 · +900%)', 300),
        mk_log('WARN',  'checkout: p95 latency 1200ms (baseline 340ms)', 240),
        mk_log('WARN',  'checkout: queue depth 340 · autoscaling kicked in', 180),
        mk_log('INFO',  'kube: scaled checkout from 8 to 24 replicas', 120),
        mk_log('INFO',  'checkout: p95 latency 620ms (still elevated but recovering)', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={
            'error_rate_pct': 0.3,  # errors low
            'p95_latency_ms': 900,
            'request_rate_per_s': 47000,
        },
    )


EXPECTATION = Expectation(
    max_issues=1,  # not really an incident, at most one "load" observation
    root_cause_does_not_contain=['bug', 'regression', 'commit', 'deploy caused'],
)
