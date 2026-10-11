"""CP1 · Org has ONLY logs enabled — no metrics/CI-CD/traces. Prompt must not hallucinate absence."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'CP1'
TIER = 2


def run(ctx):
    logs = [
        mk_log('ERROR', 'auth.jwt: token verify FAIL — kid=None', 240),
        mk_log('ERROR', 'auth.jwt: 47 verification failures in 60s', 180),
        mk_log('ERROR', 'checkout: 401 on POST /checkout/confirm (no session)', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        # Explicitly empty: no metrics, no code_changes, no alerts, no traces
        metrics_summary={},
        code_changes=[],
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['jwt', 'token', 'auth', 'session'],
    # AI must not scapegoat missing data as the root cause
    root_cause_does_not_contain=['no metrics available', 'metrics missing', 'no code changes'],
)
