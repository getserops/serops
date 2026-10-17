"""SN1 · Sentinel QUIET decision is correct.

A batch full of INFO/heartbeat log lines with no metric spikes and no
new error patterns should trigger ``sentinel_decision='quiet'``. With
active mode on, the AI must be skipped and cost saved.

The generator temporarily enables ``active_mode=True`` on the org's
SentinelConfig for the duration of the run (and restores it after)
so this test exercises the same gating logic prod would use, without
requiring the operator to hand-configure the org.

Also primes ``ProjectEnvironmentState`` with a benign baseline —
otherwise the very first evaluation on a fresh project returns
``'first'`` instead of ``'quiet'``.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'SN1'
TIER = 0


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(msg: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': 'INFO',
        'log_level': 'INFO',
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def _prime_sentinel_state(ctx):
    """Seed ProjectEnvironmentState with a benign baseline so the
    first real evaluation lands as 'quiet' not 'first'."""
    from Data.models import ProjectEnvironmentState
    from Projects.models import Project, ProjectEnvironment
    from Organisations.models import Organisations
    proj = Project.objects.get(id=ctx.project_id)
    env, _ = ProjectEnvironment.objects.get_or_create(
        project=proj, name=ctx.environment,
        defaults={'is_active': True},
    )
    org = Organisations.objects.get(id=ctx.org_id)
    state, created = ProjectEnvironmentState.objects.get_or_create(
        project=proj, environment=env,
        defaults={'organisation': org},
    )
    # Force benign baselines and mark as "not first"
    state.baseline_error_rate = 0.5
    state.baseline_memory = 42.0
    state.baseline_stddev_memory = 5.0
    state.baseline_cpu = 20.0
    state.baseline_stddev_cpu = 3.0
    state.error_counts = [0, 0, 0]
    state.batches_since_last_ai = 1  # not near max_quiet_batches
    state.known_log_patterns = {}
    state.save()
    return env


def _set_active_mode(org_id: int, active: bool):
    """Enable/disable sentinel active_mode on the org. Idempotent."""
    from Organisations.models import Organisations
    org = Organisations.objects.get(id=org_id)
    try:
        cfg = org.sentinel_config
    except Exception:
        from org_settings.models import SentinelConfig
        cfg = SentinelConfig.objects.create(organisation=org)
    cfg.active_mode = active
    cfg.save(update_fields=['active_mode'])


def run(ctx):
    from tests_gauntlet._core import create_batch, ensure_project

    ensure_project(ctx)
    _prime_sentinel_state(ctx)
    _set_active_mode(ctx.org_id, True)

    # Purely quiet content — INFO heartbeats, no errors, no metric spikes.
    logs = [_log(f'health check pass — iteration {i}', 10 - i) for i in range(10)]
    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
        metrics_summary={
            'memory': {'usage_percent': {'avg': 42.0}},
            'cpu': {'usage_percent': {'avg': 20.0}},
        },
    )


EXPECTATION = Expectation(
    sentinel_decision='quiet',
    ai_skipped_expected=True,
    # AI never ran → no issues, no analysis_text.
    max_issues=0,
    timed_out_ok=False,
)
