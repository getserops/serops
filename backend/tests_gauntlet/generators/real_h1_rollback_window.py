"""H1 · Rollback window — incident straddles two deploys.

Timeline:
  T-540 : deploy commit ``bad0dead`` (introduces the bug)
  T-420 : first errors appear
  T-300 : canary alert fires
  T-240 : auto-rollback triggered
  T-180 : deploy commit ``r0llback0`` (revert)
  T-120 : errors decrease sharply
  T-060 : batch is analysed (incident window covers both deploys)

The AI must blame ``bad0dead`` (the buggy deploy), NOT the rollback
commit ``r0llback0`` — a common failure mode when the resolver blindly
picks the most recent code_change.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'H1'
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


def run(ctx):
    from tests_gauntlet._core import create_batch

    logs = [
        _log('INFO', 'app.startup: 1.5.0 ready · commit bad0dead', 540),
        _log('WARNING', 'checkout.tax: rounding drift +0.02% over 100 tx', 460),
        _log('ERROR', 'checkout.tax: division by zero on empty cart discount', 420),
        _log('ERROR', 'checkout.tax: division by zero on empty cart discount', 380),
        _log('ERROR', 'checkout: 500 on POST /checkout/confirm', 350),
        _log('ERROR', 'canary metrics degraded · error rate 27%', 300),
        _log('INFO', 'canary alert triggered · triggering auto-rollback', 260),
        _log('INFO', 'kube.deploy: rolling back checkout to 1.4.9 · commit r0llback0', 220),
        _log('INFO', 'app.startup: 1.4.9 ready · commit r0llback0', 180),
        _log('INFO', 'error rate falling · post-rollback 3%', 120),
        _log('INFO', 'error rate 0.4% · normal', 60),
    ]

    code_changes = [
        {
            'sha': 'bad0dead',
            'commit_sha': 'bad0dead',
            'author': 'dev-bob',
            'message': (
                'refactor(checkout): simplify tax rounding logic\n\n'
                'Removes the empty-cart guard on discount computation.'
            ),
            'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=580)).isoformat(),
            'files_changed': ['services/checkout/tax.py'],
        },
        {
            'sha': 'r0llback0',
            'commit_sha': 'r0llback0',
            'author': 'ops-bot',
            'message': (
                'Revert "refactor(checkout): simplify tax rounding logic"\n\n'
                'This reverts commit bad0deadb1e5.'
            ),
            'timestamp': (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat(),
            'files_changed': ['services/checkout/tax.py'],
        },
    ]

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={'error_rate_pct': 27.0, 'p95_latency_ms': 4200},
        code_changes=code_changes,
    )


EXPECTATION = Expectation(
    min_issues=1,
    # The AI should name the buggy deploy commit OR the tax-rounding
    # regression that came with it.
    root_cause_contains_any=[
        'bad0dead', 'tax', 'division by zero', 'rounding',
        'discount', 'empty cart',
    ],
    # It should NOT blame the rollback commit.
    root_cause_does_not_contain=['r0llback0', 'revert'],
    timed_out_ok=False,
)
