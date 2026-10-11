"""A3 · Python asyncio traceback with 'The above exception was the direct cause of ...'"""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'A3'
TIER = 3

_TRACE = """Traceback (most recent call last):
  File "/app/checkout/session.py", line 47, in get
    async with self._pool.acquire() as conn:
  File "/usr/local/lib/python3.11/site-packages/redis/asyncio/client.py", line 812, in acquire
    return await asyncio.wait_for(self._pool.get(), timeout=self.timeout)
  File "/usr/local/lib/python3.11/asyncio/tasks.py", line 490, in wait_for
    return fut.result()
redis.exceptions.ConnectionError: Error 111 connecting to redis:6379. Connection refused.

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/app/checkout/api.py", line 88, in confirm
    session = await get_session(request.headers['X-Session'])
  File "/app/checkout/session.py", line 51, in get
    raise SessionUnavailable("session store down") from e
checkout.errors.SessionUnavailable: session store down"""


def run(ctx):
    logs = []
    for i in range(3):
        for line in _TRACE.split('\n'):
            logs.append(mk_log('ERROR', line, seconds_ago=300 - i*40))
    return create_batch(ctx, short_name=BATCH_ID.lower(), logs=logs,
                        metrics_summary={'error_rate_pct': 55.0})


EXPECTATION = Expectation(
    min_issues=1, max_issues=3,
    root_cause_contains_any=['redis', 'connection', 'session'],
)
