"""E3 · Stripe 429 throttles us; error rate spikes on our side but the root is external."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'E3'
TIER = 2


def run(ctx):
    logs = [
        mk_log('WARN',  'stripe.client: 429 Too Many Requests · rate limit reached', 300),
        mk_log('WARN',  'stripe.client: X-RateLimit-Remaining=0 · reset in 45s', 280),
        mk_log('ERROR', 'stripe.client: 429 (attempt 12)', 220),
        mk_log('ERROR', 'checkout: payment step failed · upstream_error=stripe_429', 180),
        mk_log('ERROR', 'checkout: rejecting new payments · cannot reach stripe', 60),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 38.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['stripe', 'external', 'upstream', 'rate limit', '429', 'throttl'],
    # AI must not blame our code
    root_cause_does_not_contain=['our code', 'application bug'],
)
