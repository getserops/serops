"""A1 · High-volume batch with 99% noise, 1% real signal.

Real prod ingest rate is 100k events/min. Persisting all of that in
a single ``batch.data`` JSONB row is neither how prod works (the log
provider is the source of truth) nor a useful gauntlet test. What IS
useful: verify the AI + Sentinel pick out the 1% real signal buried
in a large batch of noise.

Compromise: 5 000 log lines (~50× the earlier textbook batches),
99% mundane heartbeats + healthy INFO chatter, 1% real error signal
(Redis pool exhaustion). This scales the "signal-to-noise" pressure
without blowing the row size.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
import random

from tests_gauntlet._core import Expectation

BATCH_ID = 'A1'
TIER = 1


def _t(seconds_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()


def _log(level: str, msg: str, seconds_ago: int) -> dict:
    return {
        'timestamp': _t(seconds_ago),
        '@timestamp': _t(seconds_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


_NOISE_TEMPLATES = [
    'health check ok · replicas=3/3 · uptime {u}s',
    'GET /api/health 200 · duration={d}ms',
    'GET /api/ping 200 · duration={d}ms',
    'kafka.consumer: heartbeat · lag={l}',
    'cache.metrics: hits={h} misses={m} evictions={e}',
    'session.gc: cleaned {n} expired sessions',
    'GET /api/config 200 · duration={d}ms',
    'db.connection.pool: idle=8 active=2',
]


def _noise_msg(rng) -> str:
    tpl = rng.choice(_NOISE_TEMPLATES)
    return tpl.format(
        u=rng.randint(60, 900000),
        d=rng.randint(1, 20),
        l=rng.randint(0, 3),
        h=rng.randint(4000, 6000),
        m=rng.randint(50, 200),
        e=rng.randint(0, 5),
        n=rng.randint(0, 30),
    )


def run(ctx):
    from tests_gauntlet._core import create_batch

    rng = random.Random(2026_09_20)
    logs = []
    # 4 950 lines of noise, spread across a 5-min window
    for i in range(4_950):
        logs.append(_log('INFO', _noise_msg(rng), seconds_ago=300 - (i * 300 // 4950)))

    # 50 real-signal errors clustered in a 30-second window near the tail
    for i in range(50):
        logs.append(_log(
            'ERROR',
            f'redis.pool: connection refused to redis:6379 (attempt {i + 1})',
            seconds_ago=25 - (i * 25 // 50),
        ))

    # Shuffle so the errors don't sit at the end (real ingest is interleaved)
    rng.shuffle(logs)

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={
            'error_rate_pct': 1.0,  # 50/5000
            'p95_latency_ms': 340,
        },
    )


EXPECTATION = Expectation(
    # AI must find the buried Redis pool errors even in the noise.
    min_issues=1,
    root_cause_contains=['redis'],
    # And it should NOT get sidetracked by the heartbeat/health-check
    # spam and blame "health check" or "kafka consumer" etc.
    root_cause_does_not_contain=['health check', 'kafka', 'session gc'],
    timed_out_ok=False,
)
