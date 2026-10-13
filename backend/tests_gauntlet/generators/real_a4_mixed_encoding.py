"""A4 · Mixed encoding artefacts in logs (mojibake, base64 blobs, emoji, control chars)."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'A4'
TIER = 3


def run(ctx):
    logs = [
        mk_log('ERROR', 'redis.pool: connection refused to redis:6379', 240),
        mk_log('ERROR', 'checkout: 500 · body= (bin) uid=Zm9v', 200),
        mk_log('ERROR', 'checkout: user=jos\xe9 (Latin-1 mojibake) balance=UAH', 160),
        mk_log('ERROR', 'checkout: retry #12 · emoji log 🚨🔥 · Redis unreachable', 120),
        mk_log('ERROR', 'checkout: payload b64=' + 'A'*180 + '== (truncated)', 90),
        mk_log('ERROR', 'checkout: rejecting new sessions', 30),
    ]
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 68.0})


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=['redis', 'connection'],
)
