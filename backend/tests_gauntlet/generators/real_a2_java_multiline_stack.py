"""A2 · Multi-line Java stack traces.

Real Java prod logs deliver one exception as ~40 lines: the message,
frames, ``Caused by:`` chains, ``... 17 more`` skips. If the AI groups
each line as its own issue, you get 40+ ghost issues per real bug.

This batch delivers 12 repetitions of the SAME NullPointerException
(one bad request path being retried), each ~40 lines. The correct
outcome is ONE issue via fingerprint dedup, occurrence_count ≥ 12.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'A2'
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


_STACK = """java.lang.NullPointerException: Cannot invoke "com.acme.checkout.CartService.total()" because "cart" is null
\tat com.acme.checkout.CartController.confirm(CartController.java:87)
\tat com.acme.checkout.CartController$$FastClassBySpringCGLIB.invoke(<generated>)
\tat org.springframework.cglib.proxy.MethodProxy.invoke(MethodProxy.java:218)
\tat org.springframework.aop.framework.CglibAopProxy$CglibMethodInvocation.invokeJoinpoint(CglibAopProxy.java:783)
\tat org.springframework.aop.framework.ReflectiveMethodInvocation.proceed(ReflectiveMethodInvocation.java:163)
\tat org.springframework.aop.framework.CglibAopProxy$CglibMethodInvocation.proceed(CglibAopProxy.java:753)
\tat com.acme.checkout.LoggingAspect.around(LoggingAspect.java:42)
\tat java.base/jdk.internal.reflect.NativeMethodAccessorImpl.invoke(NativeMethodAccessorImpl.java:77)
\tat java.base/java.lang.reflect.Method.invoke(Method.java:568)
\tat org.springframework.aop.aspectj.AbstractAspectJAdvice.invokeAdviceMethodWithGivenArgs(AbstractAspectJAdvice.java:637)
\t... 24 more
Caused by: com.acme.session.SessionExpiredException: Session sess-8471 not found in redis
\tat com.acme.session.RedisSessionStore.get(RedisSessionStore.java:118)
\tat com.acme.session.SessionResolver.resolve(SessionResolver.java:54)
\tat com.acme.checkout.CartLoader.load(CartLoader.java:31)
\tat com.acme.checkout.CartController.confirm(CartController.java:71)
\t... 33 more
Caused by: redis.clients.jedis.exceptions.JedisConnectionException: Failed to connect to redis:6379
\tat redis.clients.jedis.Connection.connect(Connection.java:224)
\tat redis.clients.jedis.Connection.<init>(Connection.java:64)
\tat redis.clients.jedis.JedisPool.getResource(JedisPool.java:106)
\tat com.acme.session.RedisSessionStore.get(RedisSessionStore.java:112)
\t... 37 more"""


def run(ctx):
    from tests_gauntlet._core import create_batch

    logs = []
    # 12 repetitions of the same crash — same stack, spread over 5 min
    for i in range(12):
        seconds = 300 - (i * 25)
        # Split the stack into one log per line, all sharing the same
        # timestamp within a repetition (simulates one exception dump)
        for j, line in enumerate(_STACK.split('\n')):
            level = 'ERROR' if j == 0 else 'ERROR'  # entire trace at ERROR level
            logs.append(_log(level, line, seconds_ago=seconds))
    # A handful of unrelated INFO chatter interspersed so the noise
    # is realistic
    logs.append(_log('INFO', 'app.startup: ready', 305))
    logs.append(_log('INFO', 'GET /api/health 200', 200))

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={'error_rate_pct': 65.0},
    )


EXPECTATION = Expectation(
    # 12 stack traces of the same shape should collapse to ~1 issue
    # (or a very small number — allow up to 3 for AI phrasing variance).
    min_issues=1,
    max_issues=3,
    # The AI should name the ACTUAL root cause (Redis) not the
    # NullPointerException at the top of the trace.
    root_cause_contains=['redis'],
    timed_out_ok=False,
)
