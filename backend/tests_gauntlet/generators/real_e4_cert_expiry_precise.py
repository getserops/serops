"""E4 · Cert expiry — everything works until an exact timestamp, then all TLS fails."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'E4'
TIER = 3


def run(ctx):
    logs = [
        mk_log('INFO',  'checkout: HTTPS handshake OK · cn=api.acme.cloud', 480),
        mk_log('INFO',  'checkout: HTTPS handshake OK · 47 sessions/s', 360),
        mk_log('ERROR', 'checkout: TLS handshake FAILED · certificate expired at 2026-09-20T15:59:59Z', 180),
        mk_log('ERROR', 'checkout: TLS handshake FAILED · 100% of new connections rejected', 60),
    ]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(), logs=logs,
        metrics_summary={'error_rate_pct': 100.0},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['cert', 'tls', 'expir', 'handshake'],
)
