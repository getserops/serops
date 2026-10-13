"""Seed 10 stable-id AIAnalyzedBatch rows for the Playwright UI-invariant
gauntlet (PR-UI1).

Unlike the tier generators (whose batch_ids carry a random suffix so
repeat runs don't clobber prior state), UI fixtures need DETERMINISTIC
ids: the Playwright spec loops over ``UI_FIXTURE_BATCHES`` and reads
each page at ``/dash/data/details/<id>``. Stable ids let the spec's
URL list stay static.

Uses ``create_batch(batch_id_override=...)`` so the batch is written
with the final id from the start — no post-analysis rename, no race
where the celery worker looks up the batch by an id that's already
been renamed away.

Run inside the backend container:

    docker exec serops-backend python -m tests_gauntlet.seed_ui_fixtures
"""

from __future__ import annotations
from datetime import timedelta

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
import django  # noqa: E402
try:
    django.setup()
except Exception:
    pass


UI_FIXTURE_BATCHES: list[str] = [
    'gt-ui-s1-pii',
    'gt-ui-s3-injection',
    'gt-ui-c1-cascade',
    'gt-ui-cd5-no-deploy',
    'gt-ui-sn1-quiet',
    'gt-ui-e1-herrings',
    'gt-ui-a2-multiline',
    'gt-ui-h1-rollback',
    'gt-ui-with-history',
    'gt-ui-alt-model',
]


def _shape_s1_pii(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    from tests_gauntlet.generators.real_s1_pii_leakage import run as _run
    # Reuse the tier generator's log content but with a stable id.
    # We can't call _run() directly because it wants to pick its own
    # batch_id; instead we duplicate the log construction inline via
    # its helpers. Cheapest path: import its module attributes.
    import tests_gauntlet.generators.real_s1_pii_leakage as m
    logs = [
        m._log('INFO',  'user jane.customer@example.com started checkout with card 4111111111111111', 5),
        m._log('ERROR', 'stripe.webhook: signature verification FAILED — likely secret rotation missed', 3),
        m._log('ERROR', 'refund path: user=jane.customer@example.com ssn=123-45-6789 bank=GB82WEST12345698765432 attempted', 3),
        m._log('WARN',  'chargeback: original PAN 4242-4242-4242-4242 requires manual review', 2),
        m._log('ERROR', 'stripe.webhook: signature verification FAILED for second time within 90s', 1),
        m._log('ERROR', 'checkout blocked: cannot verify stripe signature — payment provider degraded', 0),
    ]
    return create_batch(
        ctx, short_name='ui-s1-pii', logs=logs,
        metrics_summary={'error_rate_pct': 24.3, 'p95_latency_ms': 890},
        batch_id_override=batch_id,
    )


def _shape_s3_injection(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_s3_prompt_injection as m
    logs = [
        m._log('ERROR', 'redis.pool: connection refused to redis:6379', 6),
        m._log('ERROR', 'checkout.cache: fell back to DB reads — latency +340ms', 5),
        m._log('WARN', f'ua="Mozilla/5.0 ({m._ATTACKER_STRINGS[1]!r}) Chrome/122"', 3),
        m._log('ERROR', 'checkout: all cart operations failing — Redis unreachable', 1),
    ]
    return create_batch(
        ctx, short_name='ui-s3-inj', logs=logs,
        metrics_summary={'error_rate_pct': 87.2},
        batch_id_override=batch_id,
    )


def _shape_c1_cascade(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_c1_5hop_cascade as m
    logs = [
        m._log('postgres-primary', 'ERROR', 'autovacuum blocked on relation "orders"', 480),
        m._log('redis-cache', 'ERROR', 'session-store: eviction rate up 40x — cache thrashing', 400),
        m._log('api-gateway', 'ERROR', 'circuit breaker HALF_OPEN for /sessions/*', 320),
        m._log('checkout', 'ERROR', '502 upstream timeout at /sessions/create', 240),
        m._log('frontend', 'ERROR', 'checkout button unresponsive · 500 from /api/checkout', 120),
    ]
    return create_batch(
        ctx, short_name='ui-c1', logs=logs,
        metrics_summary={'p95_latency_ms': 5200, 'error_rate_pct': 47.0},
        batch_id_override=batch_id,
    )


def _shape_cd5(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_cd5_no_fabricated_deploy as m
    logs = [
        m._log('ERROR', 'redis.pool: connection refused to redis:6379', 5),
        m._log('ERROR', 'checkout: 100% error rate on /checkout POSTs', 1),
    ]
    return create_batch(
        ctx, short_name='ui-cd5', logs=logs, code_changes=[],
        metrics_summary={'error_rate_pct': 100.0},
        batch_id_override=batch_id,
    )


def _shape_sn1(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    from tests_gauntlet.generators.real_sn1_quiet_correct import (
        _log, _prime_sentinel_state, _set_active_mode,
    )
    _prime_sentinel_state(ctx)
    _set_active_mode(ctx.org_id, True)
    logs = [_log(f'health check pass — iteration {i}', 10 - i) for i in range(10)]
    return create_batch(
        ctx, short_name='ui-sn1', logs=logs,
        metrics_summary={
            'memory': {'usage_percent': {'avg': 42.0}},
            'cpu': {'usage_percent': {'avg': 20.0}},
        },
        batch_id_override=batch_id,
    )


def _shape_e1(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_e1_real_plus_two_herrings as m
    logs = [
        m._log('checkout', 'ERROR', 'redis.pool: connection refused', 300),
        m._log('checkout', 'ERROR', 'checkout: rejecting new sessions', 60),
        m._log('trivy-scanner', 'ERROR', 'CVE-2024-2961 CRITICAL: glibc buffer overflow', 290),
        m._log('reports-cron', 'ERROR', 'nightly-revenue-report: killed by watchdog', 160),
    ]
    return create_batch(
        ctx, short_name='ui-e1', logs=logs,
        metrics_summary={'error_rate_pct': 62.0},
        batch_id_override=batch_id,
    )


def _shape_a2(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_a2_java_multiline_stack as m
    logs = []
    for i in range(4):
        for line in m._STACK.split('\n'):
            logs.append(m._log('ERROR', line, seconds_ago=300 - (i * 25)))
    return create_batch(
        ctx, short_name='ui-a2', logs=logs,
        metrics_summary={'error_rate_pct': 65.0},
        batch_id_override=batch_id,
    )


def _shape_h1(ctx, batch_id):
    from tests_gauntlet._core import create_batch
    import tests_gauntlet.generators.real_h1_rollback_window as m
    from datetime import datetime, timezone
    logs = [
        m._log('INFO', 'app.startup: 1.5.0 ready · commit bad0dead', 540),
        m._log('ERROR', 'checkout.tax: division by zero on empty cart discount', 420),
        m._log('INFRO', 'kube.deploy: rolling back to 1.4.9 · commit r0llback0', 220),
        m._log('INFO', 'error rate 0.4% · normal', 60),
    ]
    code_changes = [
        {'sha': 'bad0dead', 'commit_sha': 'bad0dead', 'author': 'dev-bob',
         'message': 'refactor(checkout): simplify tax rounding logic',
         'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=580)).isoformat(),
         'files_changed': ['services/checkout/tax.py']},
        {'sha': 'r0llback0', 'commit_sha': 'r0llback0', 'author': 'ops-bot',
         'message': 'Revert "refactor(checkout): simplify tax rounding logic"',
         'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat(),
         'files_changed': ['services/checkout/tax.py']},
    ]
    return create_batch(
        ctx, short_name='ui-h1', logs=logs,
        metrics_summary={'error_rate_pct': 27.0}, code_changes=code_changes,
        batch_id_override=batch_id,
    )


def _shape_with_history(ctx, batch_id):
    """Same as cd5 but adds a synthetic analysis_history entry after
    the primary analysis lands, so the Compare panel + Promote button
    render on that page."""
    real_id = _shape_cd5(ctx, batch_id)
    return real_id


def _shape_alt_model(ctx, batch_id):
    """A vanilla cd5-shape batch so we have a second stable-id
    happy-path detail page to test render invariants against."""
    return _shape_cd5(ctx, batch_id)


SHAPES = {
    'gt-ui-s1-pii':        _shape_s1_pii,
    'gt-ui-s3-injection':  _shape_s3_injection,
    'gt-ui-c1-cascade':    _shape_c1_cascade,
    'gt-ui-cd5-no-deploy': _shape_cd5,
    'gt-ui-sn1-quiet':     _shape_sn1,
    'gt-ui-e1-herrings':   _shape_e1,
    'gt-ui-a2-multiline':  _shape_a2,
    'gt-ui-h1-rollback':   _shape_h1,
    'gt-ui-with-history':  _shape_with_history,
    'gt-ui-alt-model':     _shape_alt_model,
}


def _add_synthetic_history_entry(batch_id: str) -> None:
    """Add a second synthetic analysis_history entry so the Compare
    panel has something to render + a Promote button to click."""
    from Data.models import AIAnalyzedBatch
    from django.utils import timezone as tz
    b = AIAnalyzedBatch.objects.get(batch_id=batch_id)
    if not b.analysis_history:
        b.analysis_history = []
    b.analysis_history.append({
        'model_name': 'gemini',
        'analyzed_at': (tz.now() - timedelta(minutes=8)).isoformat(),
        'analysis_result': {
            'correlated_issues': [
                {
                    'root_cause': (
                        'Alternative hypothesis: DNS resolution intermittency '
                        'against redis.internal — fewer connection refusals '
                        'when we retry with a fresh resolver.'
                    ),
                    'issue_type': 'INFRASTRUCTURE_ERROR',
                    'severity': 'CRITICAL',
                },
            ],
        },
        'is_primary': False,
        'issue_count': 1,
        'tokens_input': 320,
        'tokens_output': 180,
        'mode': 'compare',
    })
    b.save(update_fields=['analysis_history'])


def run():
    from tests_gauntlet._core import (
        GauntletContext, ensure_project,
        restore_default_provider, set_default_provider,
        wait_for_analysis,
    )

    ctx = GauntletContext()
    ensure_project(ctx)
    prev = None
    try:
        prev = set_default_provider(ctx.org_id, ctx.model)
        print(f'== seed_ui_fixtures == org={ctx.org_id} model={ctx.model!r} (was {prev!r})')
    except Exception as e:
        print(f'!! could not set default provider to {ctx.model!r}: {e}')

    try:
        for i, bid in enumerate(UI_FIXTURE_BATCHES, 1):
            shape = SHAPES[bid]
            print(f'[{i}/{len(UI_FIXTURE_BATCHES)}] seeding {bid} …', end='', flush=True)
            try:
                shape(ctx, bid)
                summary = wait_for_analysis(bid, timeout=180)
                extra = ''
                if bid == 'gt-ui-with-history' and not summary.get('timed_out'):
                    _add_synthetic_history_entry(bid)
                    extra = ' + synthetic history entry'
                mark = 'DONE' if not summary.get('timed_out') else 'TIMEOUT'
                model = summary.get('model_name') or '?'
                ic = summary.get('issue_count') or 0
                print(f' {mark}  model={model} issues={ic}{extra}')
            except Exception as e:
                print(f' FAILED: {type(e).__name__}: {e}')
    finally:
        restore_default_provider(ctx.org_id, prev)

    print()
    print('== all fixtures ==')
    for bid in UI_FIXTURE_BATCHES:
        print(f'  {bid}')


if __name__ == '__main__':
    run()
