"""B2 · Deploy status=success but rollout stalled at 40% pods; alerts firing."""
from tests_gauntlet._core import Expectation, create_batch, mk_log
BATCH_ID = 'B2'
TIER = 2


def run(ctx):
    logs = [
        mk_log('INFO',  'kube.deploy: rollout status SUCCESS · commit fee15fee', 480),
        mk_log('WARN',  'kube.deploy: only 4/10 pods READY at 300s · rolling forward', 400),
        mk_log('ERROR', 'kube.deploy: 6 pods CrashLoopBackOff on new image', 350),
        mk_log('ERROR', 'checkout: 500 on POST /checkout/confirm (backend fleet degraded)', 200),
        mk_log('ERROR', 'checkout: p95 latency 6100ms (target 300)', 90),
    ]
    code_changes = [{
        'sha': 'fee15fee', 'commit_sha': 'fee15fee',
        'author': 'dev-carol',
        'message': 'chore(checkout): bump base image to python:3.13-alpine',
    }]
    return create_batch(
        ctx, short_name=BATCH_ID.lower(),
        logs=logs, code_changes=code_changes,
        metrics_summary={'error_rate_pct': 41.0, 'p95_latency_ms': 6100},
    )


EXPECTATION = Expectation(
    min_issues=1,
    root_cause_contains_any=[
        'fee15fee', 'deploy', 'rollout', 'crashloop', 'crash loop',
        'python', 'image', 'commit',
    ],
)
