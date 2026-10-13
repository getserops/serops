"""Chaos-RCA scenarios.

Each entry injects a fault whose cause is KNOWN because we caused it, lets
real logs / metrics / traces accumulate, then scores whether the RCA named
that cause.

Declarative on purpose. The previous gauntlet hand-wrote log text containing
the answer ("PaymentGatewayTimeout upstream=stripe"), which measured string
extraction rather than diagnosis. Here the workload emits symptoms only — a
timeout, a 503, an RSS number — and the cause has to come from which service
degraded, what its metrics did, and where the trace spent its time.

Scoring dimensions, each independently pass/fail:

  root_cause_any   at least one phrase appears in narrative + issue text
  component_any    at least one issue blames one of these components
  must_not_say     none of these phrases appear (catches confident misblame)
  sentinel_analysed  Sentinel chose to run the AI (decision `first` or
                     `alert`). Not a specific label: state is reset per
                     scenario so each is judged independently, which makes
                     `first` the correct decision — asserting `alert` would
                     test the harness rather than the product.
  min_issues       at least this many issues raised

`inject` is a list of (service, fault_dict) applied in order. `repeat`
re-applies the injection every few seconds for faults that need to
accumulate (a leak grows only when requests arrive).
"""

SCENARIOS = [
    # ---------------------------------------------------------------- Tier A
    {
        'name': 'a01_cache_memory_exhaustion',
        'tier': 'A',
        'description': 'cache grows RSS past its 96Mi limit until the kubelet OOMKills it',
        'inject': [('cache', {'leak_mb': 14})],
        'soak': 150,
        'expect': {
            'root_cause_any': ['memory', 'oom', 'rss', 'limit', 'exhaust'],
            'component_any': ['cache'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },
    {
        'name': 'a02_cache_latency',
        'tier': 'A',
        'description': 'cache adds 1.5s per call; checkout and api slow down but do not error',
        'inject': [('cache', {'latency_ms': 1500})],
        'soak': 120,
        'expect': {
            'root_cause_any': ['latenc', 'slow', 'delay', 'respons', 'timeout', 'duration'],
            'component_any': ['cache', 'api', 'checkout'],
            'min_issues': 1,
        },
    },
    {
        'name': 'a03_cache_refuses_connections',
        'tier': 'A',
        'description': 'cache returns 503 for every request; api and checkout cascade',
        'inject': [('cache', {'refuse': True})],
        'soak': 110,
        'expect': {
            'root_cause_any': ['cache', 'depend', 'unavail', '503', 'upstream', 'downstream'],
            'component_any': ['cache', 'api'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },
    {
        'name': 'a04_api_cpu_saturation',
        'tier': 'A',
        'description': 'api burns 700ms of CPU per request, saturating its 500m limit',
        'inject': [('api', {'cpu_ms': 700})],
        'soak': 130,
        'expect': {
            'root_cause_any': ['cpu', 'satur', 'throttl', 'slow', 'latenc', 'resource'],
            'component_any': ['api', 'checkout'],
            'min_issues': 1,
        },
    },
    {
        'name': 'a05_checkout_unhandled_exception',
        'tier': 'A',
        'description': 'checkout raises on every request — a code-level failure, not infra',
        'inject': [('checkout', {'exception': 'NullReferenceError in order pipeline'})],
        'soak': 110,
        'expect': {
            'root_cause_any': ['exception', 'unhandled', 'error', 'fail', 'checkout'],
            'component_any': ['checkout'],
            'must_not_say': ['out of memory', 'oomkill'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },
    {
        'name': 'a06_dependency_dns_failure',
        'tier': 'A',
        'description': 'api points at a hostname that does not resolve',
        'inject': [('api', {'__env__': {'DOWNSTREAM_URL': 'http://cache-typo.production.svc.cluster.local:8080'}})],
        'soak': 120,
        'expect': {
            'root_cause_any': ['resolv', 'dns', 'unreach', 'connect', 'depend', 'name'],
            'component_any': ['api', 'checkout'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },
    {
        'name': 'a07_cache_scaled_to_zero',
        'tier': 'A',
        'description': 'cache has no running pods — connection refused, not a slow response',
        'inject': [('__scale__', {'deployment': 'cache', 'replicas': 0})],
        'soak': 110,
        'expect': {
            'root_cause_any': ['refus', 'unreach', 'unavail', 'connect', 'cache', 'depend'],
            'component_any': ['cache', 'api', 'checkout'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },
    {
        'name': 'a08_pool_exhaustion',
        'tier': 'A',
        'description': 'api holds one worker slot while cache is slow, so requests queue',
        'inject': [
            ('cache', {'latency_ms': 2500}),
            ('api', {'__env__': {'POOL_SIZE': '1'}}),
        ],
        'soak': 130,
        'expect': {
            'root_cause_any': ['timeout', 'queue', 'pool', 'satur', 'latenc', 'slow', 'capacity'],
            'component_any': ['api', 'cache', 'checkout'],
            'min_issues': 1,
        },
    },
    {
        'name': 'a09_partial_error_rate',
        'tier': 'A',
        'description': 'checkout fails 40% of requests — degradation, not an outage',
        'inject': [('checkout', {'error_rate': 0.4})],
        'soak': 120,
        'expect': {
            'root_cause_any': ['error', 'fail', 'checkout', 'intermitt', 'partial', 'rate'],
            'component_any': ['checkout'],
            'min_issues': 1,
        },
    },
    {
        'name': 'a10_timeout_too_tight',
        'tier': 'A',
        'description': 'checkout timeout cut to 250ms while api legitimately takes ~600ms',
        'inject': [
            ('api', {'latency_ms': 600}),
            ('checkout', {'downstream_timeout_s': 0.25}),
        ],
        'soak': 120,
        'expect': {
            'root_cause_any': ['timeout', 'exceed', 'latenc', 'slow', 'api', 'depend'],
            'component_any': ['checkout', 'api'],
            'sentinel_analysed': True,
            'min_issues': 1,
        },
    },

    # ---------------------------------------------------------------- Tier B
    # Correlations that need real multi-signal data — the class a synthetic
    # log-injection harness cannot produce at all.
    {
        'name': 'b01_latency_only_in_traces',
        'tier': 'B',
        'description': 'cache slows by 900ms but logs nothing abnormal; only trace duration reveals it',
        'inject': [('cache', {'latency_ms': 900})],
        'soak': 140,
        'expect': {
            'root_cause_any': ['cache', 'latenc', 'slow', 'duration', 'trace', 'respons'],
            'component_any': ['cache', 'api', 'checkout'],
            'min_issues': 1,
        },
        'notes': 'cache emits only INFO "request completed status=200" — the '
                 'degradation exists in span duration and nowhere else.',
    },
    {
        'name': 'b02_gradual_leak_then_oom',
        'tier': 'B',
        'description': 'slow RSS growth produces a metric trend before any error log appears',
        'inject': [('api', {'leak_mb': 5})],
        'soak': 200,
        'expect': {
            'root_cause_any': ['memory', 'grow', 'leak', 'rss', 'oom', 'limit'],
            'component_any': ['api'],
            'min_issues': 1,
        },
    },
    {
        'name': 'b03_three_tier_cascade',
        'tier': 'B',
        'description': 'cache fails; api and checkout both error. Must blame cache, not its victims',
        'inject': [('cache', {'exception': 'storage engine unavailable'})],
        'soak': 130,
        'expect': {
            'root_cause_any': ['cache', 'depend', 'upstream', 'downstream', 'cascad'],
            'component_any': ['cache'],
            'min_issues': 2,
        },
        'notes': 'The discriminating test: all three services log errors. '
                 'Naming checkout (the most visible) instead of cache (the '
                 'origin) is the classic RCA failure.',
    },
    {
        'name': 'b04_deploy_coincides_with_unrelated_fault',
        'tier': 'B',
        'description': 'a deployment lands while cache independently degrades — is the deploy wrongly blamed?',
        'inject': [
            ('__deploy__', {'deployment': 'checkout'}),
            ('cache', {'latency_ms': 1200}),
        ],
        'soak': 140,
        'expect': {
            'root_cause_any': ['cache', 'latenc', 'slow', 'depend'],
            'component_any': ['cache', 'api', 'checkout'],
            'min_issues': 1,
        },
        'notes': 'Sentinel will fire deployment_detected. A correct answer '
                 'attributes the slowness to cache; blaming the checkout '
                 'rollout is a false correlation.',
    },

    # ---------------------------------------------------------------- Tier C
    {
        'name': 'c01_two_unrelated_incidents',
        'tier': 'C',
        'description': 'cache leaks memory AND checkout throws — two causes, must not be conflated',
        'inject': [
            ('cache', {'leak_mb': 12}),
            ('checkout', {'exception': 'order serialisation failed'}),
        ],
        'soak': 150,
        'expect': {
            'root_cause_any': ['memory', 'exception', 'checkout', 'cache'],
            'component_any': ['cache', 'checkout'],
            'min_issues': 2,
        },
        'notes': 'Two distinct issues expected. One merged issue blaming a '
                 'single cause is the failure mode.',
    },
    {
        'name': 'c02_red_herring_noise',
        'tier': 'C',
        'description': 'cache is the real fault; loadgen emits unrelated error noise at volume',
        'inject': [
            ('cache', {'refuse': True}),
            ('loadgen', {'error_rate': 1.0}),
        ],
        'soak': 130,
        'expect': {
            'root_cause_any': ['cache', 'depend', 'unavail', '503', 'upstream'],
            'component_any': ['cache', 'api', 'checkout'],
            'must_not_say': ['load generator is the root cause'],
            'min_issues': 1,
        },
    },
    {
        'name': 'c03_healthy_window',
        'tier': 'C',
        'description': 'nothing wrong at all — Sentinel should stay quiet and no issue should be invented',
        'inject': [],
        'soak': 120,
        'expect': {
            'max_issues': 0,
        },
        'notes': 'The false-positive test. Inventing a root cause from a '
                 'healthy window is worse than missing one, because it '
                 'trains operators to ignore the tool.',
    },
    {
        'name': 'c04_signal_source_down',
        'tier': 'C',
        'description': 'cache errors while the metrics provider is unreachable — degrade, do not crash',
        'inject': [
            ('cache', {'exception': 'storage timeout'}),
            ('__break_metrics__', {}),
        ],
        'soak': 120,
        'expect': {
            'root_cause_any': ['cache', 'error', 'fail', 'depend', 'timeout'],
            'min_issues': 1,
        },
        'notes': 'Must still produce an answer from logs and traces alone, '
                 'and must not raise.',
    },
]
