"""B3 · Alert fires but log shipper is 30 min behind; batch has no logs."""
from tests_gauntlet._core import Expectation, create_batch
BATCH_ID = 'B3'
TIER = 3


def run(ctx):
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=[],
        # Alert-like metadata
        metrics_summary={'error_rate_pct': 41.0, 'log_shipper_lag_minutes': 30},
        alerts=[{
            'alertname': 'HighErrorRate', 'state': 'firing',
            'service': 'checkout', 'environment': 'production',
            'summary': 'HighErrorRate on checkout · 41% error rate',
        }],
    )


EXPECTATION = Expectation(
    # AI must not fabricate a root cause without evidence
    max_issues=1,
    root_cause_does_not_contain=['fabricated', 'invented'],
)
