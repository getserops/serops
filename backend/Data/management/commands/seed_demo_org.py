"""
seed_demo_org — build a read-only demo organisation populated with a
realistic 7-day operational story.

This command powers the public demo at https://app.serops.ai. It is
also useful when you self-host SerOps: running it once on a fresh
instance gives you a fully populated org so you can explore every
dashboard, drill into issues, and read pre-canned chat investigations
without first having to wire up real observability providers.

What it creates (all flagged ``is_demo=True``):

  - Organisations row "Acme Cloud" with one demo user (viewer role)
  - 2 projects: acme-checkout and acme-platform
  - 5 services (3 application + 2 infrastructure)
  - 7 days of AI-analyzed batches across dev / staging / production
  - A coherent story arc — deploys → incidents → resolutions
  - ~12 issues (mix OPEN / RESOLVED / MUTED, including 3 CRITICAL)
  - 6 deployments with realistic code-change diffs
  - 3 pre-populated chat sessions showing AI investigation
  - Sentinel decisions that produce a believable 60-70 % skip rate
  - Cost tracking (AITokenUsage) so the "Saved this week" hero stat
    on the Sentinel dashboard widget has real numbers to display

The command is **idempotent** — running it twice is safe. It wipes the
demo org's mutable data and rebuilds the story, but never touches any
other organisation.

Usage::

    python manage.py seed_demo_org             # fresh-build / nightly reset
    python manage.py seed_demo_org --dry-run   # report what would change

Centerpiece incident
--------------------
A Database connection-pool exhaustion on 2026-D-3 caused by deploy
v2.3.3, which shrank the pool from 50 to 20 connections. The AI traces
it back through commit ``a3f1d8c`` and links the metric anomaly to the
deploy time. The chat session shows the AI ruling out an upstream
provider as the cause.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from Organisations.models import Organisations
from Users.models import User
from Projects.models import Project, ProjectService, SCMBinding, CICDBinding, ProjectDeployment
from providers.models import Pipeline, Job, CodeChange, Deployment, ProviderIntegration
from Data.models import AIAnalyzedBatch, Issue, AuditLog, AlertEvent
from ai_model.models import ChatSession, ChatMessage, AITokenUsage
from integrations.models import ObservabilityIntegration, Cluster, IntegrationScope
from notifications.models import (
    Notification, ProjectSubscription, EscalationRule,
    IncidentNotificationChannel,
)
from org_settings.models import OrganisationAISettings, AIModelProvider
from traces.models import IngestKey


# ---------------------------------------------------------------------------
# Constants — pinned values so the demo is reproducible across runs
# ---------------------------------------------------------------------------

DEMO_ORG_NAME = 'Acme Cloud'
DEMO_ORG_SLUG = 'acme-cloud'

DEMO_USER_EMAIL = 'demo@serops.ai'
DEMO_USER_USERNAME = 'demo'

# The demo org's AI provider. Gemini, because that is the provider the demo
# host actually holds a key for — the story should show what a visitor's own
# instance would plausibly run, not a provider nothing here is configured
# with. The model name is read from the provider catalogue at seed time so it
# follows org_settings' default-model migrations instead of going stale; the
# fallback only applies on an install whose catalogue has no gemini row.
DEMO_AI_PROVIDER = 'gemini'
DEMO_AI_MODEL_FALLBACK = 'gemini-3.6-flash'


def _demo_ai_model() -> str:
    provider = AIModelProvider.objects.filter(name=DEMO_AI_PROVIDER).first()
    return (provider.default_model if provider and provider.default_model
            else DEMO_AI_MODEL_FALLBACK)
DEMO_USER_PASSWORD = 'demo'  # the demo is publicly accessible; password is informational

# Sentinel value stored in place of real credentials on demo integration
# records. Serializers detect this string and mask the response so no
# secret material ever leaves the API, and the health-check endpoint
# short-circuits to synthetic OK when it sees this value — the hosts
# don't exist and we don't want the demo box making outbound requests.
SEED_DEMO_PLACEHOLDER = 'SEED_DEMO_PLACEHOLDER_NOT_A_REAL_SECRET'

# Pre-seeded "engineers" so the chat history feels human.
DEMO_AUTHORS = [
    ('Sarah Chen', 'sarah.chen@acme.cloud'),
    ('Marc Dubois', 'marc.dubois@acme.cloud'),
    ('Priya Ramanathan', 'priya.r@acme.cloud'),
]

PROJECT_CHECKOUT = 'acme-checkout'
PROJECT_PLATFORM = 'acme-platform'

# (project_name, service_name, service_type, subtype, description)
DEMO_SERVICES = [
    (PROJECT_CHECKOUT, 'backend-api', 'application', 'backend',
     'Django REST API powering the checkout flow.'),
    (PROJECT_CHECKOUT, 'payment-worker', 'application', 'worker',
     'Celery worker for asynchronous payment-gateway calls.'),
    (PROJECT_CHECKOUT, 'web-frontend', 'application', 'frontend',
     'React + Vite single-page app served via CDN.'),
    (PROJECT_PLATFORM, 'postgres-primary', 'infrastructure', 'database',
     'Primary PostgreSQL cluster for checkout + platform data.'),
    (PROJECT_PLATFORM, 'redis-cache', 'infrastructure', 'cache',
     'Redis cluster used as the payment-worker queue and session store.'),
]


# ---------------------------------------------------------------------------
# Story scenes — declarative, ordered chronologically
# ---------------------------------------------------------------------------

@dataclass
class Scene:
    """One step in the demo story arc.

    Each scene describes a deploy or an incident that happened N days
    ago. The seed turns it into batches + issues + (optionally) a
    Pipeline/CodeChange row. Keeping it declarative makes the arc easy
    to tweak without touching the rendering code.
    """
    days_ago: int
    deploy_sha: str | None
    deploy_message: str | None
    environment: str
    # Issue spec: None to skip
    issue_type: str | None = None
    issue_component: str | None = None
    issue_severity: str | None = None
    issue_status: str = 'OPEN'
    issue_description: str = ''
    issue_root_cause: str = ''
    issue_recommendation: str = ''
    issue_reasoning: list | None = None
    issue_confidence: str = 'MEDIUM'
    sentinel_decision: str = 'alert'
    is_centerpiece: bool = False
    # Whether this is a "boring quiet day" with no issues
    quiet: bool = False


STORY_ARC: list[Scene] = [
    Scene(
        days_ago=7,
        deploy_sha='f0aabb01',
        deploy_message='chore(deps): bump axios 1.7.2 → 1.7.3',
        environment='production',
        sentinel_decision='quiet',
        quiet=True,
    ),
    Scene(
        days_ago=6,
        deploy_sha=None,
        deploy_message=None,
        environment='production',
        sentinel_decision='quiet',
        quiet=True,
    ),
    Scene(
        days_ago=5,
        deploy_sha='b2c4d8e3',
        deploy_message='feat(backend): batch payment-webhook acks (#1247)',
        environment='production',
        issue_type='MEMORY_HIGH',
        issue_component='backend-api',
        issue_severity='WARNING',
        issue_status='RESOLVED',
        issue_description='Backend memory crept from 55 % to 88 % over 3 hours after deploy.',
        issue_root_cause=(
            'The webhook-batching change in v2.3.2 introduced an in-memory '
            'pandas DataFrame that accumulates rows without bound — a slow '
            'memory leak under steady traffic.'
        ),
        issue_recommendation=(
            'Cap the DataFrame at 10k rows per worker and flush to disk '
            'between batches. Patch in PR #1252.'
        ),
        issue_reasoning=[
            'Saw memory grow linearly on backend-api after 14:02 UTC',
            'Cross-referenced with deploys — only v2.3.2 landed in that window',
            'Diffed v2.3.1 → v2.3.2: payment_webhooks.py introduces an unbounded list',
            'Confirmed leak hypothesis by replaying staging traffic locally',
        ],
        issue_confidence='HIGH',
        sentinel_decision='alert',
    ),
    Scene(
        days_ago=4,
        deploy_sha='c1e9f7d2',
        deploy_message='fix(backend): cap webhook DataFrame at 10k rows (#1252)',
        environment='production',
        sentinel_decision='quiet',
        quiet=True,
    ),
    Scene(
        days_ago=3,
        deploy_sha='a3f1d8c0',
        deploy_message='perf(infra): shrink redis pool 50→20 to save memory',
        environment='production',
        issue_type='CONNECTION_REFUSED',
        issue_component='redis-cache',
        issue_severity='CRITICAL',
        issue_status='OPEN',
        issue_description='payment-worker throwing ConnectionRefusedError to redis:6379 (p95).',
        issue_root_cause=(
            'Deploy v2.3.3 reduced the Redis connection pool from 50 to 20. '
            'Under current production load this saturates the pool within '
            '~4 minutes, after which workers cannot acquire a connection.'
        ),
        issue_recommendation=(
            'Revert the pool size to 50 (PR #1259) and add a Prometheus '
            'alert on redis_pool_used > 80 % so this fails loud next time.'
        ),
        issue_reasoning=[
            'Saw repeated ConnectionRefusedError in payment-worker logs after 13:58 UTC',
            'Checked deploys — v2.3.3 reduced the Redis pool from 50 to 20',
            'Pulled Redis metrics: redis_pool_used hit 100 % within 4 min of the deploy',
            'Ruled out upstream payment-provider issue — their status page is green '
            'and other queues backed by the same Redis are unaffected',
        ],
        issue_confidence='HIGH',
        is_centerpiece=True,
        sentinel_decision='alert',
    ),
    Scene(
        days_ago=2,
        deploy_sha='e7d3b201',
        deploy_message='hotfix(backend): query timeout 5s → 30s for monthly aggregates',
        environment='production',
        issue_type='DATABASE_ERROR',
        issue_component='backend-api',
        issue_severity='CRITICAL',
        issue_status='OPEN',
        issue_description='Slow analytics queries triggering PostgreSQL `canceling statement` errors.',
        issue_root_cause=(
            'The hotfix in v2.3.4 raised the per-query timeout to 30 s but '
            'a single long-running monthly-aggregate query now holds a row '
            'lock that blocks checkout writes.'
        ),
        issue_recommendation=(
            'Move the monthly aggregate to a read replica and lower the '
            'primary timeout back to 5 s. See PR #1264.'
        ),
        issue_reasoning=[
            'Saw `canceling statement due to statement timeout` errors',
            'Traced the timeouts to the aggregate query introduced in v2.3.4',
            'Confirmed it is holding row locks long enough to back up checkout writes',
        ],
        issue_confidence='MEDIUM',
        sentinel_decision='alert',
    ),
    Scene(
        days_ago=1,
        deploy_sha='9be4cc55',
        deploy_message='style(web): tighten button hierarchy on checkout',
        environment='production',
        sentinel_decision='quiet',
        quiet=True,
    ),
    Scene(
        days_ago=0,
        deploy_sha=None,
        deploy_message=None,
        environment='production',
        issue_type='CPU_HIGH',
        issue_component='postgres-primary',
        issue_severity='WARNING',
        issue_status='OPEN',
        issue_description='Postgres CPU drifted from 35 % baseline to 78 % over 2 h.',
        issue_root_cause=(
            'Sustained CPU rise correlates with increased vacuum activity. '
            'Likely caused by yesterday\'s missing index on payment_events.'
        ),
        issue_recommendation='Create btree index on payment_events.created_at.',
        issue_reasoning=[
            'CPU climbed steadily without a corresponding traffic increase',
            'pg_stat_activity shows long-running autovacuum on payment_events',
            'Table has 12M rows and no index on the column being scanned',
        ],
        issue_confidence='MEDIUM',
        sentinel_decision='alert',
    ),
    # Staging signal — different env, milder issue, MUTED status
    Scene(
        days_ago=2,
        deploy_sha=None,
        deploy_message=None,
        environment='staging',
        issue_type='TEST_FAILED',
        issue_component='backend-api',
        issue_severity='INFO',
        issue_status='MUTED',
        issue_description='Flaky integration test on staging (intermittent timeout).',
        issue_root_cause='Test is racing against a fixture cleanup teardown.',
        issue_recommendation='Add explicit `await` on the cleanup future.',
        issue_reasoning=[
            'Failure rate is ~5% across the last 100 staging runs',
            'No production impact — only staging fixture race',
        ],
        issue_confidence='LOW',
        sentinel_decision='quiet',
    ),
    # Dev-environment signal — adds a third environment to the filter
    # dropdown and a benign chat-friendly issue on the frontend service.
    Scene(
        days_ago=3,
        deploy_sha='dev12345',
        deploy_message='chore(web): bump vite 5 → 6 in local dev',
        environment='development',
        issue_type='BUILD_WARNING',
        issue_component='web-frontend',
        issue_severity='INFO',
        issue_status='RESOLVED',
        issue_description='Vite 6 emits a peer-dep warning for @vitejs/plugin-react.',
        issue_root_cause='Plugin lags one major version behind Vite core.',
        issue_recommendation='Pin @vitejs/plugin-react to ^5 until it publishes v6.',
        issue_reasoning=['warning is dev-only, no runtime impact'],
        issue_confidence='LOW',
        sentinel_decision='quiet',
    ),
]


# ---------------------------------------------------------------------------
# Component → project routing
# ---------------------------------------------------------------------------
# Which project each service belongs to. Used so infra-service issues
# (postgres, redis) create batches under acme-platform instead of
# defaulting everything to acme-checkout.
COMPONENT_TO_PROJECT = {
    'backend-api': PROJECT_CHECKOUT,
    'payment-worker': PROJECT_CHECKOUT,
    'web-frontend': PROJECT_CHECKOUT,
    'postgres-primary': PROJECT_PLATFORM,
    'redis-cache': PROJECT_PLATFORM,
}


# ---------------------------------------------------------------------------
# Synthetic payloads — logs, cicd logs, metrics, correlations
# ---------------------------------------------------------------------------
#
# SerOps normally *queries* logs from an observability provider at
# batch-analysis time, then persists the raw hits inside ``batch.data``
# so the Batch Details drill-down can show them without re-querying.
# The demo host has no real provider (all Integrations are seeded
# placeholders), so we manufacture the hits directly here — matching
# the ES-hit shape the frontend expects (Detail.jsx + data.service.js
# adaptor).

def _synthetic_logs(scene: 'Scene', scene_time: datetime, project_name: str) -> list:
    """Return 6 ES-hit-shaped log documents matching the scene narrative.

    Every scene gets a couple of INFO lines so the log tab isn't just
    scary errors; scenes with an issue also get 3 ERROR lines that
    match the issue's root cause, so a demo visitor can immediately
    see the evidence backing the AI's analysis.
    """
    service = scene.issue_component or 'backend-api'
    base_ts = scene_time.replace(microsecond=0)
    index = f'app-logs-{scene_time.strftime("%Y.%m.%d")}'

    entries = [
        ('INFO', f'GET /api/health/ 200 12ms'),
        ('INFO', f'{service} healthy — {random_seed_choice(scene, ["200 OK", "connection acquired", "cache hit"])}'),
    ]
    if scene.issue_type and not scene.quiet:
        # Three error lines that echo the scene's issue narrative so
        # the log page and the AI analysis feel like the same story.
        error_map = {
            'MEMORY_HIGH': [
                'memory_usage_percent: 88.4 (breach threshold 85.0)',
                'DataFrame webhook_batch grew to 47320 rows without flush',
                'GC pressure high — pandas.core.frame.DataFrame instances count=12k',
            ],
            'CONNECTION_REFUSED': [
                'ConnectionRefusedError: [Errno 111] connect to redis:6379',
                'redis.exceptions.ConnectionError: max pool size reached (20/20)',
                'payment-worker: no free redis connection — dropping task',
            ],
            'DATABASE_ERROR': [
                'psycopg.errors.QueryCanceled: canceling statement due to statement timeout',
                'lock on relation "payment_events" held for 31s by pid 4472',
                'checkout write blocked — waiting for row lock on payment_events',
            ],
            'CPU_HIGH': [
                'postgres cpu_usage_percent: 78.2 (baseline 35)',
                'autovacuum on payment_events running for 480s',
                'seq_scan_per_second: 340 (typical 15) on payment_events',
            ],
            'TEST_FAILED': [
                'FAIL tests/integration/test_payment_flow.py::test_webhook_race',
                'AssertionError: expected 200, got 504 (staging fixture teardown)',
                'pytest: 1 failed, 132 passed, 3 skipped in 214.71s',
            ],
            'BUILD_WARNING': [
                'npm WARN peerDependencies @vitejs/plugin-react wants vite@^5',
                'vite v6.0.0 building for development...',
                'built in 3.42s (warnings=1)',
            ],
        }
        for msg in error_map.get(scene.issue_type, ['error observed']):
            entries.append(('ERROR', msg))

    docs = []
    for i, (level, message) in enumerate(entries):
        ts = base_ts + timedelta(seconds=i * 7)
        docs.append({
            '_index': index,
            '_id': f'{scene.days_ago}d-{i}-{service}',
            '_source': {
                '@timestamp': ts.isoformat().replace('+00:00', 'Z'),
                'message': message,
                'level': level,
                'service_name': service,
                'organisation_name': DEMO_ORG_NAME,
                'project_name': project_name,
                'environment': scene.environment,
                'log_level': level,
            },
        })
    return docs


def _synthetic_cicd_logs(scene: 'Scene', scene_time: datetime,
                          pipeline_id_str: str) -> list:
    """Return 1–2 CI/CD log records matching the deploy in this scene.

    Shape matches what data.service.js#getBatchLogs expects for the
    ``cicd_logs`` array + what Data.unified_timeline._events_from_cicd
    reads (finished_at → timeline event time).
    """
    if not scene.deploy_sha:
        return []
    job_name = 'build-and-test'
    branch = 'main' if scene.environment == 'production' else scene.environment
    is_failed = scene.issue_severity == 'CRITICAL' and scene.issue_status == 'OPEN'
    # Deploy pipeline started ~10 min before the batch window end and
    # ran for ~2 min. Real timestamps let the CI/CD event plot on the
    # timeline chart at a plausible position relative to the deploy.
    started = scene_time - timedelta(minutes=10)
    finished = scene_time - timedelta(minutes=8)
    return [{
        'job_id': f'{scene.deploy_sha}-build',
        'job_name': job_name,
        'status': 'failed' if is_failed else 'success',
        'branch': branch,
        'pipeline_id': pipeline_id_str,
        'commit_sha': scene.deploy_sha,
        'commit_message': scene.deploy_message,
        'message': f'{job_name} on {branch}: {scene.deploy_message or "no message"}',
        'trace': (
            f'++ set -eux\n++ npm ci\n++ npm test\n'
            f'PASS  tests/unit\n'
            + ('FAIL  tests/integration/test_payment_flow.py\n' if is_failed else '')
            + f'{"exit 1" if is_failed else "exit 0"}\n'
        ),
        'started_at': started.isoformat(),
        'finished_at': finished.isoformat(),
        'timestamp': finished.isoformat(),  # legacy consumers
        'service_name': scene.issue_component or 'backend-api',
    }]


def _synthetic_metrics(scene: 'Scene', scene_time: datetime) -> dict:
    """12-point memory + cpu time series per batch.

    Shape matches what data.service.js#getBatchMetrics expects:
    ``data.metrics.memory_usage_percent`` and ``cpu_usage_percent``,
    each a list of ``{time, value, source_table}`` dicts.
    """
    base = scene_time.replace(microsecond=0)
    # Baseline series
    mem_baseline = 55.0
    cpu_baseline = 30.0
    # Bumps aligned with issue narrative
    if scene.issue_type == 'MEMORY_HIGH':
        mem_curve = [55, 58, 62, 66, 71, 75, 78, 81, 84, 87, 88, 86]
    elif scene.issue_type == 'CPU_HIGH':
        mem_curve = [55] * 12
    else:
        mem_curve = [max(45, mem_baseline + i * 0.5) for i in range(12)]
    if scene.issue_type == 'CPU_HIGH':
        cpu_curve = [35, 38, 42, 48, 55, 61, 66, 70, 73, 76, 78, 76]
    elif scene.issue_type == 'CONNECTION_REFUSED':
        cpu_curve = [30, 32, 34, 45, 62, 71, 68, 55, 40, 33, 30, 30]
    else:
        cpu_curve = [max(20, cpu_baseline + (i - 6) * 0.8) for i in range(12)]

    def _series(curve, source):
        return [
            {
                'time': (base + timedelta(minutes=i * 5)).isoformat().replace('+00:00', 'Z'),
                'value': round(float(v), 2),
                'source_table': source,
            }
            for i, v in enumerate(curve)
        ]

    return {
        'memory_usage_percent': _series(mem_curve, 'node_memory'),
        'cpu_usage_percent': _series(cpu_curve, 'node_cpu'),
    }


def _synthetic_correlations(scene: 'Scene') -> dict:
    """Correlation results in the engine's canonical shape.

    Matches what ``Data.correlation_engine.build_comprehensive_correlations``
    returns at runtime — a dict with a ``correlations`` sub-dict
    keyed by correlation type, plus a ``summary``. The timeline
    endpoint's ``build_causal_pairs`` reads this to draw engine-
    backed arrows on the chart (Batch 42).

    Prior shape was a flat list of {component, metric, correlation_strength}
    which no frontend or backend consumer actually read. The chart
    fell back to a naive time-window heuristic and the demo shipped
    without any engine-backed arrows.
    """
    if scene.quiet or not scene.issue_type or not scene.deploy_sha:
        # No correlations without both an issue AND a deploy — the
        # engine needs both endpoints to draw a causal arrow.
        return {
            'correlations': {
                'file_to_error': [],
                'deployment_to_metric_spike': [],
                'metric_spike_to_errors': [],
                'span_error_to_log_error': [],
                'slow_span_after_deploy': [],
                'slow_span_during_metric_spike': [],
            },
            'summary': {
                'total_correlations': 0,
                'high_confidence_count': 0,
                'primary_correlation': None,
            },
        }

    # Component-aware storytelling — different scenes get different
    # correlation types so the timeline shows variety.
    component = scene.issue_component or 'backend-api'
    sha_short = scene.deploy_sha[:8]

    file_to_error = []
    deployment_to_metric_spike = []
    slow_span_after_deploy = []

    if scene.issue_type in ('MEMORY_HIGH', 'CONNECTION_REFUSED', 'DATABASE_ERROR', 'CPU_HIGH'):
        # deploy caused a metric anomaly — the flagship visual pair.
        metric_map = {
            'MEMORY_HIGH': ('memory', '88%'),
            'CONNECTION_REFUSED': ('memory', '76%'),
            'DATABASE_ERROR': ('cpu', '94%'),
            'CPU_HIGH': ('cpu', '92%'),
        }
        metric_type, peak = metric_map[scene.issue_type]
        deployment_to_metric_spike.append({
            'confidence': 'HIGH',
            'metric_type': metric_type,
            'anomaly_peak': peak,
            'time_after_deploy_minutes': 8.5,
            'commit_sha': sha_short,
        })

    if scene.issue_type in ('CONNECTION_REFUSED', 'DATABASE_ERROR', 'MEMORY_HIGH'):
        # deploy also caused error logs referencing changed files.
        file_map = {
            'CONNECTION_REFUSED': ['config/redis.py'],
            'DATABASE_ERROR': ['db/queries.py', 'models/orders.py'],
            'MEMORY_HIGH': ['api/payment_webhooks.py'],
        }
        file_to_error.append({
            'confidence': 'HIGH',
            'commit_sha': sha_short,
            'matching_files': file_map[scene.issue_type],
            'time_since_commit_minutes': 12.0,
            'log_message': f'Error in {component}',
        })

    # slow_span_after_deploy — pairs the deploy with a trace error span
    # (matches the seeded batch.data.traces content).
    slow_span_after_deploy.append({
        'confidence': 'MEDIUM',
        'commit_sha': sha_short,
        'services_affected': [component],
        'top_slow_service': component,
        'top_slow_operation': f'op on {component}',
        'top_slow_duration_ms': 3120,
        'trace_id': 'f0e1d2c3b4a5968778695a4b3c2d1e0f',
    })

    total = len(file_to_error) + len(deployment_to_metric_spike) + len(slow_span_after_deploy)
    high = sum(
        1 for group in (file_to_error, deployment_to_metric_spike, slow_span_after_deploy)
        for c in group if c.get('confidence') == 'HIGH'
    )
    primary_type = 'file_to_error' if file_to_error else (
        'deployment_to_metric_spike' if deployment_to_metric_spike else 'slow_span_after_deploy'
    )

    return {
        'correlations': {
            'file_to_error': file_to_error,
            'deployment_to_metric_spike': deployment_to_metric_spike,
            'metric_spike_to_errors': [],
            'span_error_to_log_error': [],
            'slow_span_after_deploy': slow_span_after_deploy,
            'slow_span_during_metric_spike': [],
        },
        'summary': {
            'total_correlations': total,
            'high_confidence_count': high,
            'primary_correlation': {'type': primary_type, 'details': {}},
        },
    }


def _synthetic_traces(scene: 'Scene', scene_time: datetime) -> dict | None:
    """OTLP trace summary the way ``ai_model.trace_context`` writes it.

    Shape matches ``batch.data.traces`` produced at ingest time (see
    trace_context.build_trace_context). BatchTraces reads it directly.

    Returns None for quiet batches so those legitimately render the
    "no snapshot in this window" state — matching production where a
    batch that never got trace data gets no key rather than an empty
    dict.
    """
    if scene.quiet:
        return None

    # Two representative traces per batch — one slow, one erroring.
    # trace_id / span_id length matches OTLP hex spec (32 / 16 chars).
    trace_slow = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
    trace_err = 'f0e1d2c3b4a5968778695a4b3c2d1e0f'

    # Component-aware content so different scenes tell different
    # trace stories rather than looking cloned.
    component = scene.issue_component or 'backend-api'
    component_traits = {
        'backend-api': {
            'service': 'backend-api',
            'slow_op': 'POST /checkout/complete',
            'slow_ms': 1840,
            'err_op': 'POST /checkout/complete',
            'err_msg': 'unhandled exception: MemoryError',
        },
        'payment-worker': {
            'service': 'payment-worker',
            'slow_op': 'consume payment.pending',
            'slow_ms': 4200,
            'err_op': 'redis.set(cache_key)',
            'err_msg': 'ConnectionRefusedError: redis pool exhausted',
        },
        'redis-cache': {
            'service': 'payment-worker',
            'slow_op': 'redis.get(session)',
            'slow_ms': 950,
            'err_op': 'redis.set(cache_key)',
            'err_msg': 'ConnectionRefusedError: redis pool exhausted',
        },
        'postgres-primary': {
            'service': 'backend-api',
            'slow_op': 'SELECT orders WHERE user_id = $1',
            'slow_ms': 3120,
            'err_op': 'INSERT INTO orders',
            'err_msg': 'deadlock detected',
        },
        'web-frontend': {
            'service': 'web-frontend',
            'slow_op': 'GET /api/checkout/summary',
            'slow_ms': 2200,
            'err_op': 'GET /api/checkout/summary',
            'err_msg': 'upstream timeout: backend-api',
        },
    }
    t = component_traits.get(component, component_traits['backend-api'])

    services_touched = sorted({t['service'], 'backend-api', 'web-frontend'})

    # start_time positions each span on the timeline chart. Anchoring
    # them just before the batch window end matches the "these errors
    # were surfaced by this batch" mental model.
    slow_start = (scene_time - timedelta(minutes=4)).isoformat()
    err_start = (scene_time - timedelta(minutes=2)).isoformat()

    top_slow = [
        {
            'service_name': t['service'],
            'operation_name': t['slow_op'],
            'duration_ms': t['slow_ms'],
            'trace_id': trace_slow,
            'span_id': '1122334455667788',
            'start_time': slow_start,
        },
        {
            'service_name': 'web-frontend',
            'operation_name': 'render CheckoutSummary',
            'duration_ms': int(t['slow_ms'] * 0.6),
            'trace_id': trace_slow,
            'span_id': '2233445566778899',
            'start_time': slow_start,
        },
    ]

    top_errors = [
        {
            'service_name': t['service'],
            'operation_name': t['err_op'],
            'status_message': t['err_msg'],
            'trace_id': trace_err,
            'span_id': 'aabbccddeeff0011',
            'start_time': err_start,
        },
    ] if scene.issue_type else []

    return {
        'source': 'otlp',
        'span_count': 47,
        'error_span_count': 3 if scene.issue_type else 0,
        'trace_count': 12,
        'services_touched': services_touched,
        'top_slow': top_slow,
        'top_errors': top_errors,
    }


def random_seed_choice(scene: 'Scene', options: list) -> str:
    """Deterministic pick — hashing scene.days_ago keeps the demo stable across reruns."""
    return options[scene.days_ago % len(options)]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

class Command(BaseCommand):
    help = 'Build (or rebuild) the public read-only Acme Cloud demo org.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what would change without writing anything.',
        )

    def handle(self, *args, **opts):
        if opts['dry_run']:
            self.stdout.write(self.style.NOTICE(
                '[dry-run] Would rebuild the Acme Cloud demo org and its 7-day story arc.'
            ))
            return

        with transaction.atomic():
            org = self._upsert_org()
            user = self._upsert_user(org)
            projects = self._upsert_projects(org)
            services = self._upsert_services(projects)
            # Clusters must exist before integrations so we can pin
            # some integrations to a specific cluster (Item #17-19,
            # Q1.4 multi-cluster wiring).
            clusters = self._upsert_clusters(org, projects)
            self._upsert_project_topology(projects, clusters)
            self._upsert_integrations(org, services, clusters)
            self._upsert_ingest_key(org)
            self._upsert_incident_channels(org)
            self._upsert_ai_budget(org)

            # Wipe the mutable content. This is what makes nightly reset
            # safe — projects, services, and the user remain stable so
            # their IDs do not churn, but issues/batches/chats/code
            # changes are torn down and rebuilt.
            self._wipe_dynamic_content(org)

            self._build_story_arc(org, projects, services)

        self.stdout.write(self.style.SUCCESS(
            f"Demo org '{org.name}' rebuilt: "
            f"{Project.objects.filter(organisation=org).count()} projects, "
            f"{ProjectService.objects.filter(project__organisation=org).count()} services, "
            f"{Cluster.objects.filter(organisation=org).count()} clusters, "
            f"{ProjectDeployment.objects.filter(project__organisation=org).count()} deployments, "
            f"{AIAnalyzedBatch.objects.filter(organisation=org).count()} batches, "
            f"{Issue.objects.filter(organisation=org).count()} issues, "
            f"{AlertEvent.objects.filter(organisation=org).count()} alert events, "
            f"{IncidentNotificationChannel.objects.filter(organisation=org).count()} incident channels, "
            f"{ChatSession.objects.filter(user=user).count()} chat sessions."
        ))

    # ── Org / user / project / service ────────────────────────────────

    def _upsert_org(self) -> Organisations:
        from Organisations.models import OnboardingStatus

        org, _ = Organisations.objects.update_or_create(
            slug=DEMO_ORG_SLUG,
            defaults={
                'name': DEMO_ORG_NAME,
                'website': 'https://demo.serops.ai',
                'language': 'en',
                'is_demo': True,
            },
        )
        # Mark onboarding as finished so visitors land directly on the
        # dashboard instead of the wizard. The demo org's projects /
        # services / integrations are already wired by this command.
        status, _ = OnboardingStatus.objects.get_or_create(organisation=org)
        if not status.is_completed:
            status.is_completed = True
            status.current_step = 'completed'
            status.completed_at = timezone.now()
            status.completed_steps = [
                'connect_integration', 'create_project',
                'link_service', 'configure_logs',
            ]
            status.save()
        return org

    def _upsert_user(self, org: Organisations) -> User:
        user, created = User.objects.get_or_create(
            email=DEMO_USER_EMAIL,
            defaults={
                'username': DEMO_USER_USERNAME,
                'first_name': 'SerOps',
                'last_name': 'Demo',
                'role': 'admin',
                'is_active': True,
                'is_demo': True,
                'organisation': org,
            },
        )
        if not created:
            # Keep mutable fields aligned even on re-runs.
            user.username = DEMO_USER_USERNAME
            # admin role so demo visitors can *see* admin pages (Team,
            # Audit Log, Sentinel, AI settings, etc.). Writes are still
            # blocked by DemoUserMiddleware regardless of role — that
            # middleware is the security boundary here, not RBAC.
            user.role = 'admin'
            user.is_active = True
            user.is_demo = True
            user.organisation = org
            user.save()
        user.set_password(DEMO_USER_PASSWORD)
        user.save(update_fields=['password'])
        return user

    def _upsert_projects(self, org: Organisations) -> dict[str, Project]:
        projects: dict[str, Project] = {}
        for project_name in (PROJECT_CHECKOUT, PROJECT_PLATFORM):
            proj, _ = Project.objects.update_or_create(
                name=project_name,
                organisation=org,
                defaults={
                    'description': (
                        'Customer checkout flow — Django backend, React frontend, Celery payment worker.'
                        if project_name == PROJECT_CHECKOUT
                        else 'Shared platform infra — PostgreSQL primary, Redis cache.'
                    ),
                },
            )
            projects[project_name] = proj
        return projects

    def _upsert_services(self, projects: dict[str, Project]) -> dict[str, ProjectService]:
        services: dict[str, ProjectService] = {}
        for proj_name, name, svc_type, subtype, description in DEMO_SERVICES:
            svc, _ = ProjectService.objects.update_or_create(
                project=projects[proj_name],
                name=name,
                defaults={
                    'service_type': svc_type,
                    'subtype': subtype,
                    'description': description,
                    'status': 'Active',
                },
            )
            services[name] = svc
        return services

    # ── Integrations ───────────────────────────────────────────────────

    def _upsert_integrations(
        self,
        org: Organisations,
        services: dict[str, ProjectService],
        clusters: dict[str, Cluster] | None = None,
    ) -> None:
        """Populate Settings → Integrations *and* wire each application
        service to a plausible repo + pipeline via SCMBinding / CICDBinding.

        Without this, a demo visitor sees a rich dashboard and then an
        empty Integrations page (org-level integrations) *and* empty
        Service Details panels (per-service repo/pipeline links). Both
        read as "the data is fake / the product is broken". These
        records ship with the sentinel placeholder credential
        SEED_DEMO_PLACEHOLDER — serializers detect it and mask
        everything the UI would otherwise show, and the health-check
        endpoint short-circuits to synthetic OK so nothing actually
        calls out to hosts that don't exist.

        Idempotent: safe to re-run; existing rows are updated in place.
        """
        now = timezone.now()
        prod_cluster = (clusters or {}).get('prod-eks') if clusters else None
        stg_cluster = (clusters or {}).get('staging-gke') if clusters else None

        # Wipe existing observability integrations for this org so the
        # new tier/scope-sliced rows don't stack on top of the old
        # (org, provider)-keyed rows from pre-Batch-48 seed runs.
        # Idempotent + safe: this seed is the sole author of these rows
        # in the demo org.
        ObservabilityIntegration.objects.filter(organisation=org).delete()

        # --- Observability providers ---
        # Batch 55: seed a mixed-tier, mixed-scope shape so the multi-row
        # Observability panel (Batch 53) has interesting rows to render
        # and the composed filter (Batch 54) has real dimensions to
        # scope by. Primary rows cover the golden path; a fallback and
        # a tertiary row demonstrate the failover chain badge.
        obs_specs = [
            # Prod-EKS · us-east-1 · primary logs
            {
                'provider': 'elasticsearch',
                'display_name': 'Elasticsearch · prod primary',
                'capabilities': ['logs'],
                'host': 'https://es.acme.cloud:9200',
                'username': 'serops',
                'cluster_key': 'prod-eks',
                'priority_tier': 'primary',
                'scope': {'environment': 'production', 'region': 'us-east-1'},
            },
            # Prod-EKS · fallback logs (Loki takes over if ES stalls)
            {
                'provider': 'loki',
                'display_name': 'Loki · prod fallback',
                'capabilities': ['logs'],
                'host': 'https://loki.acme.cloud',
                'extra_config': {'tenant_id': 'acme-cloud'},
                'cluster_key': 'prod-eks',
                'priority_tier': 'fallback',
                'scope': {'environment': 'production', 'region': 'us-east-1'},
                'topology_mode': 'kubernetes',
            },
            # Staging-GKE · eu-west-1 · primary logs+metrics via Datadog
            {
                'provider': 'datadog',
                'display_name': 'Datadog · staging',
                'capabilities': ['logs', 'metrics'],
                'host': 'https://api.datadoghq.com',
                'extra_config': {'site': 'datadoghq.com', 'app_key': SEED_DEMO_PLACEHOLDER},
                'cluster_key': 'staging-gke',
                'priority_tier': 'primary',
                'scope': {'environment': 'staging', 'region': 'europe-west1'},
            },
            # Prod-EKS · primary metrics
            {
                'provider': 'prometheus',
                'display_name': 'Prometheus · prod primary',
                'capabilities': ['metrics'],
                'host': 'https://prom.acme.cloud',
                'cluster_key': 'prod-eks',
                'priority_tier': 'primary',
                'scope': {'environment': 'production', 'region': 'us-east-1'},
                'topology_mode': 'kubernetes',
            },
            # Prod-EKS · fallback metrics — VictoriaMetrics as HA backup
            {
                'provider': 'victoriametrics',
                'display_name': 'VictoriaMetrics · prod fallback',
                'capabilities': ['metrics'],
                'host': 'https://vm.acme.cloud',
                'cluster_key': 'prod-eks',
                'priority_tier': 'fallback',
                'scope': {'environment': 'production', 'region': 'us-east-1'},
                'topology_mode': 'kubernetes',
            },
            # Unscoped · tertiary — CloudWatch catches anything the
            # cluster-scoped rows miss. Demonstrates the "any-cluster
            # tertiary fallback" path in the failover chain.
            {
                'provider': 'cloudwatch',
                'display_name': 'AWS CloudWatch · tertiary',
                'capabilities': ['logs', 'metrics'],
                'host': 'https://logs.us-east-1.amazonaws.com',
                'extra_config': {
                    'aws_region': 'us-east-1',
                    'aws_access_key_id': SEED_DEMO_PLACEHOLDER,
                    'default_log_group': '/acme/production',
                },
                'cluster_key': None,
                'priority_tier': 'tertiary',
                'scope': {},
            },
        ]

        cluster_lookup = {
            'prod-eks': prod_cluster,
            'staging-gke': stg_cluster,
            None: None,
        }

        for spec in obs_specs:
            defaults = {
                'display_name': spec['display_name'],
                'capabilities': spec['capabilities'],
                'host': spec['host'],
                'username': spec.get('username', ''),
                'extra_config': spec.get('extra_config', {}),
                'priority_tier': spec.get('priority_tier', 'primary'),
                'is_active': True,
                'last_health_check': now,
                'last_health_status': True,
            }
            cluster = cluster_lookup.get(spec.get('cluster_key'))
            if cluster is not None:
                defaults['cluster'] = cluster
            if 'topology_mode' in spec:
                defaults['topology_mode'] = spec['topology_mode']
            obj, _ = ObservabilityIntegration.objects.update_or_create(
                organisation=org,
                provider=spec['provider'],
                cluster=cluster,
                priority_tier=defaults['priority_tier'],
                defaults=defaults,
            )
            obj.set_password(SEED_DEMO_PLACEHOLDER)
            obj.save()

            # Hydrate the IntegrationScope (Batch 48) — env/region/ns
            # dimensions so the composed filter has non-empty pills
            # to render on the multi-row panel.
            scope_spec = spec.get('scope') or {}
            scope, _ = IntegrationScope.objects.get_or_create(integration=obj)
            scope.environment = scope_spec.get('environment', '')
            scope.region = scope_spec.get('region', '')
            scope.namespace = scope_spec.get('namespace', '')
            scope.cluster = cluster
            scope.save()

        # --- SCM / CI-CD providers (3 rows) ---
        scm_specs = [
            {
                'provider_type': 'github',
                'name': 'GitHub · acme-corp',
                'category': 'devops',
                'base_url': 'https://api.github.com',
                'capabilities': ['scm', 'cicd', 'deployments', 'issues'],
                'token_hint': 'ghp_…demo',
            },
            {
                'provider_type': 'gitlab',
                'name': 'GitLab Self-Hosted · acme.cloud',
                'category': 'devops',
                'base_url': 'https://gitlab.acme.cloud',
                'capabilities': ['scm', 'cicd', 'deployments'],
                'token_hint': 'glpat…demo',
            },
            {
                'provider_type': 'jenkins',
                'name': 'Jenkins · platform-ci',
                'category': 'cicd',
                'base_url': 'https://ci.acme.cloud',
                'capabilities': ['cicd'],
                'token_hint': '11a…demo',
            },
        ]
        for spec in scm_specs:
            ProviderIntegration.objects.update_or_create(
                organisation=org,
                provider_type=spec['provider_type'],
                defaults={
                    'name': spec['name'],
                    'category': spec['category'],
                    'base_url': spec['base_url'],
                    'capabilities': spec['capabilities'],
                    'credentials': {'access_token': SEED_DEMO_PLACEHOLDER},
                    'token_hint': spec['token_hint'],
                    'verification_status': 'verified',
                    'last_verified_at': now,
                    'is_active': True,
                },
            )

        # --- Per-service bindings ---
        # Each application service gets an SCM binding (repo) and a
        # CI/CD binding (pipeline). Infra services (postgres, redis)
        # stay unbound — that matches the "you'd only wire code to a
        # repo, not a database" reality.
        github = ProviderIntegration.objects.get(organisation=org, provider_type='github')
        gitlab = ProviderIntegration.objects.get(organisation=org, provider_type='gitlab')
        jenkins = ProviderIntegration.objects.get(organisation=org, provider_type='jenkins')

        # (service_key, repo_name, repo_id, cicd_integration, pipeline_id, pipeline_name)
        binding_specs = [
            ('backend-api', 'acme-corp/backend-api', 'acme-corp/backend-api',
             gitlab, '842', 'backend-api :: build+deploy'),
            ('payment-worker', 'acme-corp/payment-worker', 'acme-corp/payment-worker',
             jenkins, 'job/payment-worker/build', 'payment-worker · build'),
            ('web-frontend', 'acme-corp/web-frontend', 'acme-corp/web-frontend',
             gitlab, '843', 'web-frontend :: build+deploy'),
        ]
        for svc_key, repo_name, repo_id, cicd_int, pipeline_id, pipeline_name in binding_specs:
            svc = services.get(svc_key)
            if not svc:
                continue

            SCMBinding.objects.update_or_create(
                project_service=svc,
                defaults={
                    'integration': github,
                    'repository_id': repo_id,
                    'repository_name': repo_name,
                    'repository_url': f'https://github.com/{repo_name}',
                    'default_branch': 'main',
                    'webhook_configured': True,
                    'last_sync_at': now,
                },
            )

            CICDBinding.objects.update_or_create(
                project_service=svc,
                integration=cicd_int,
                pipeline_id=pipeline_id,
                defaults={
                    'binding_type': 'build',
                    'pipeline_name': pipeline_name,
                    'pipeline_url': (
                        f'{cicd_int.base_url}/-/pipelines/{pipeline_id}'
                        if cicd_int.provider_type == 'gitlab'
                        else f'{cicd_int.base_url}/{pipeline_id}'
                    ),
                    'auto_trigger': True,
                    'trigger_branches': ['main'],
                    'webhook_configured': True,
                },
            )

    # ── Clusters (Item #17-19, Q1.4) ──────────────────────────────────

    def _upsert_clusters(
        self,
        org: Organisations,
        projects: dict[str, Project],
    ) -> dict[str, Cluster]:
        """Create two demo clusters + wire the checkout project to prod.

        Multi-cluster is one of the recent-launch storytelling angles
        (Batches 17-19, 25). Without seeded clusters the multi-cluster
        picker, per-cluster dashboard filter, and cluster-aware routing
        all show empty states — the demo undersells the feature.
        """
        cluster_specs = [
            {
                'name': 'prod-eks',
                'description': 'Production EKS cluster in AWS us-east-1. '
                               'Runs the checkout stack + payment workers.',
                'provider': 'eks',
                'region': 'us-east-1',
                'kubernetes_context': 'arn:aws:eks:us-east-1:123456789012:cluster/prod-eks',
            },
            {
                'name': 'staging-gke',
                'description': 'Staging GKE cluster in GCP europe-west1. '
                               'Mirrors production topology for load tests.',
                'provider': 'gke',
                'region': 'europe-west1',
                'kubernetes_context': 'gke_acme-cloud_europe-west1_staging',
            },
        ]
        clusters: dict[str, Cluster] = {}
        for spec in cluster_specs:
            cluster, _ = Cluster.objects.update_or_create(
                organisation=org,
                name=spec['name'],
                defaults={
                    'description': spec['description'],
                    'provider': spec['provider'],
                    'region': spec['region'],
                    'kubernetes_context': spec['kubernetes_context'],
                    'is_active': True,
                },
            )
            clusters[spec['name']] = cluster

        # Wire the checkout project to prod-eks so the cluster picker
        # actually filters something. Platform project stays unassigned
        # to demonstrate the fallback path.
        checkout = projects.get(PROJECT_CHECKOUT)
        if checkout is not None:
            checkout.cluster = clusters['prod-eks']
            checkout.save(update_fields=['cluster'])

        return clusters

    # ── Environments + Deployments (Batches 48-52) ────────────────────

    def _upsert_project_topology(
        self,
        projects: dict[str, Project],
        clusters: dict[str, Cluster],
    ) -> None:
        """Seed envs + multi-deployment topology so the Deployments tab
        (Batch 52) and multi-row Observability panel (Batch 53) have
        interesting content instead of empty states.

        Direct ORM ``Project.objects.update_or_create`` upstream skips
        the serializer's ``create_default_environments`` call, so we
        materialise envs here explicitly. The env post_save signal
        (Batches 48-49) auto-creates one deployment per active env; we
        then layer extra deployments on the checkout project to
        demonstrate multi-region + namespace-scoped shapes.

        Idempotent — safe to re-run.
        """
        from Projects.models import ProjectEnvironment

        # Envs for both projects — matches the story arc scenes that
        # reference production / staging / development.
        env_specs = [
            ('production', 'Production', True),
            ('staging',    'Staging',    True),
            ('development','Development',True),
        ]
        # Wipe legacy env=None deployments (leftovers from the pre-
        # env-signal flow when a project had a cluster but no envs).
        # They stack awkwardly next to the per-env rows below.
        for proj in projects.values():
            ProjectDeployment.objects.filter(
                project=proj, environment__isnull=True,
            ).delete()

        for proj in projects.values():
            for name, display, active in env_specs:
                ProjectEnvironment.objects.get_or_create(
                    project=proj,
                    name=name,
                    defaults={
                        'display_name': display,
                        'is_active': active,
                        'log_label_value': name,
                    },
                )
            # If the project was created before we added envs, the signal
            # never fired — kick per-env deployment creation now.
            for env in proj.environments.filter(is_active=True):
                ProjectDeployment.objects.get_or_create(
                    project=proj, environment=env, cluster=proj.cluster,
                    region='', namespace='',
                    defaults={'is_active': True},
                )

        # Multi-deployment topology for the checkout project: primary
        # prod on prod-eks/us-east-1 (auto-created above), plus a
        # namespace-scoped copy for the payments squad, plus a
        # secondary-region copy on staging-gke/europe-west1.
        checkout = projects.get(PROJECT_CHECKOUT)
        if checkout is not None:
            prod_env = checkout.environments.filter(name='production').first()
            staging_env = checkout.environments.filter(name='staging').first()

            if prod_env and clusters.get('prod-eks'):
                ProjectDeployment.objects.get_or_create(
                    project=checkout,
                    environment=prod_env,
                    cluster=clusters['prod-eks'],
                    region='us-east-1',
                    namespace='payments',
                    defaults={'is_active': True},
                )
            if staging_env and clusters.get('staging-gke'):
                ProjectDeployment.objects.get_or_create(
                    project=checkout,
                    environment=staging_env,
                    cluster=clusters['staging-gke'],
                    region='europe-west1',
                    namespace='',
                    defaults={'is_active': True},
                )

    # ── OTLP ingest key (Item #10) ────────────────────────────────────

    def _upsert_ingest_key(self, org: Organisations) -> None:
        """Ensure one active OTLP IngestKey exists so Settings → Traces
        renders a real row instead of the empty state.

        The plaintext key is thrown away — only the hash is stored
        (GitHub PAT model). Callers who want a working plaintext for
        collector-config screenshots can regenerate in the UI. This
        seeded key exists solely to make the settings page look alive.
        """
        # Idempotent by name — if a key already exists, leave it alone
        # (its hash is stable across rebuilds).
        if IngestKey.objects.filter(organisation=org, name='prod-eks-otel-collector').exists():
            return
        plaintext = IngestKey.generate_key()
        key = IngestKey(
            organisation=org,
            name='prod-eks-otel-collector',
            is_active=True,
        )
        key.set_key(plaintext)
        key.save()

    # ── Incident notification channels (Items #22, #23) ───────────────

    def _upsert_incident_channels(self, org: Organisations) -> None:
        """Seed one Slack + one PagerDuty + one OpsGenie channel so
        Settings → Incident Channels + the post-RCA dispatch story
        both show real rows.

        Credentials are the sentinel placeholder — encrypted at rest
        exactly like a real value, but the dispatcher's ``send()``
        short-circuits when it detects the placeholder so nothing
        actually hits Slack/PagerDuty from the demo host.
        """
        channel_specs = [
            {
                'name': 'SRE Slack (#incidents)',
                'kind': 'slack',
                'webhook_url': f'https://hooks.slack.com/services/{SEED_DEMO_PLACEHOLDER}',
                'api_key': '',
                'extra_config': {'channel': '#incidents'},
                'trigger_events': ['batch_analyzed'],
                'min_severity': 'MEDIUM',
            },
            {
                'name': 'Prod PagerDuty',
                'kind': 'pagerduty',
                'webhook_url': '',
                'api_key': SEED_DEMO_PLACEHOLDER,
                'extra_config': {},
                # PagerDuty is the "paging" surface — filter aggressively
                # so we don't burn oncall on every scheduled batch.
                'trigger_events': ['alert_triggered', 'critical_issue'],
                'min_severity': 'HIGH',
            },
            {
                'name': 'OpsGenie · platform team',
                'kind': 'opsgenie',
                'webhook_url': '',
                'api_key': SEED_DEMO_PLACEHOLDER,
                'extra_config': {'region': 'us'},
                'trigger_events': ['alert_triggered'],
                'min_severity': 'HIGH',
            },
        ]
        for spec in channel_specs:
            channel, _ = IncidentNotificationChannel.objects.update_or_create(
                organisation=org,
                name=spec['name'],
                defaults={
                    'kind': spec['kind'],
                    'extra_config': spec['extra_config'],
                    'trigger_events': spec['trigger_events'],
                    'min_severity': spec['min_severity'],
                    'is_active': True,
                },
            )
            # Encrypted setters — round-trip via the model's own helpers
            # so the ciphertext format matches what production writes.
            if spec['webhook_url']:
                channel.set_webhook_url(spec['webhook_url'])
            if spec['api_key']:
                channel.set_api_key(spec['api_key'])
            channel.save()

    # ── AI cost budget (Batch 26, Q3.3) ───────────────────────────────

    def _upsert_ai_budget(self, org: Organisations) -> None:
        """Seed a modest monthly budget so Settings → AI Providers
        shows a real gauge instead of "no budget set". Some AITokenUsage
        rows get written by the story-arc batches — those + this cap
        drive the current-spend and warn-threshold indicators.
        """
        # Anchor to whichever AI provider actually exists (0011 seeds
        # gemini/ollama/claude/openai/deepseek). If none exists on a
        # fresh install, leave the settings row unpopulated — the
        # budget still works without a default provider selected.
        default_provider = AIModelProvider.objects.filter(
            name=DEMO_AI_PROVIDER,
        ).first() or AIModelProvider.objects.filter(is_active=True).first()

        OrganisationAISettings.objects.update_or_create(
            organisation=org,
            defaults={
                'default_provider': default_provider,
                'monthly_budget_usd': Decimal('100.00'),
                'budget_warn_pct': 80,
                'use_custom_keys': False,
            },
        )

    # ── Alert events (Items #13, #14) ─────────────────────────────────

    def _seed_alert_events(
        self,
        org: Organisations,
        batches_by_component: dict[str, AIAnalyzedBatch],
    ) -> None:
        """Back-fill a handful of alert events so Settings → Alerts
        (or wherever the alert list lives) and the "this batch was
        triggered by …" link on the batch detail page both look real.

        Links each alert to the batch that "triggered" it via the
        ``triggered_batch`` FK — that's the wiring the on-demand
        pipeline uses in production.
        """
        now = timezone.now()

        alert_specs = [
            {
                'source': 'alertmanager',
                'external_id': 'AM-8f31c9e2',
                'alertname': 'RedisPoolExhaustion',
                'state': 'firing',
                'severity': 'critical',
                'service': 'redis-cache',
                'environment': 'production',
                'summary': 'Redis connection pool at 100% utilisation for 4 minutes. '
                           'Downstream: payment-worker seeing ConnectionRefusedError.',
                'batch_component': 'redis-cache',
                'received_offset_hours': 4,
            },
            {
                'source': 'grafana',
                'external_id': 'GRF-7a2e1d',
                'alertname': 'BackendMemoryClimb',
                'state': 'resolved',
                'severity': 'warning',
                'service': 'backend-api',
                'environment': 'production',
                'summary': 'backend-api memory usage climbed from 55% to 88% over 3h — '
                           'linear trajectory suggests unbounded accumulation.',
                'batch_component': 'backend-api',
                'received_offset_hours': 48,
            },
            {
                'source': 'datadog',
                'external_id': 'DD-monitor-33421',
                'alertname': 'PostgresSlowQueries',
                'state': 'firing',
                'severity': 'high',
                'service': 'postgres-primary',
                'environment': 'production',
                'summary': 'p95 query latency > 500ms sustained for 10min on '
                           'checkout schema — suspect missing index or table bloat.',
                'batch_component': 'postgres-primary',
                'received_offset_hours': 12,
            },
        ]
        for spec in alert_specs:
            batch = batches_by_component.get(spec['batch_component'])
            AlertEvent.objects.create(
                organisation=org,
                source=spec['source'],
                external_id=spec['external_id'],
                alertname=spec['alertname'],
                state=spec['state'],
                severity=spec['severity'],
                service=spec['service'],
                environment=spec['environment'],
                summary=spec['summary'],
                raw_payload={'demo': True, 'seeded': True},
                triggered_batch=batch,
                processed_at=now - timedelta(hours=spec['received_offset_hours']),
            )

    # ── Wipe / rebuild ─────────────────────────────────────────────────

    def _wipe_dynamic_content(self, org: Organisations) -> None:
        """Drop every mutable row scoped to the demo org so the rebuild
        starts from a clean slate. Projects, services, clusters, and
        the user survive so their IDs and FKs remain stable for
        downstream links.

        The IncidentNotificationChannel / IngestKey / AI budget rows
        are managed by the ``_upsert_*`` helpers (update_or_create)
        rather than wiped here — they carry keyed identifiers we want
        to keep stable across rebuilds. AlertEvent is wiped though
        because each rebuild produces a fresh set tied to the new
        batches.
        """
        Notification.objects.filter(user__organisation=org).delete()
        ProjectSubscription.objects.filter(user__organisation=org).delete()
        EscalationRule.objects.filter(organisation=org).delete()
        AuditLog.objects.filter(organisation=org).delete()
        ChatMessage.objects.filter(chat_session__user__organisation=org).delete()
        ChatSession.objects.filter(user__organisation=org).delete()
        AITokenUsage.objects.filter(organisation=org).delete()
        AlertEvent.objects.filter(organisation=org).delete()
        Issue.objects.filter(organisation=org).delete()
        AIAnalyzedBatch.objects.filter(organisation=org).delete()
        # Deployments cascade from CodeChange, so kill them explicitly
        # first so nothing races the CodeChange delete.
        Deployment.objects.filter(code_change__organisation=org).delete()
        CodeChange.objects.filter(organisation=org).delete()
        Pipeline.objects.filter(organisation=org).delete()

    def _build_story_arc(
        self,
        org: Organisations,
        projects: dict[str, Project],
        services: dict[str, ProjectService],
    ) -> None:
        now = timezone.now()
        issues_by_component: dict[str, Issue] = {}
        # Track the last batch per component so alert events can point
        # at the right ``triggered_batch`` in the wiring below.
        batches_by_component: dict[str, AIAnalyzedBatch] = {}
        critical_issues: list[Issue] = []

        for scene_index, scene in enumerate(STORY_ARC):
            scene_time = now - timedelta(days=scene.days_ago, hours=2)
            # Route to the project that owns the affected service. Infra
            # scenes (postgres, redis) end up under acme-platform; app
            # scenes stay in acme-checkout. Prevents acme-platform from
            # looking dead.
            project_name = COMPONENT_TO_PROJECT.get(
                scene.issue_component or 'backend-api', PROJECT_CHECKOUT
            )
            project = projects[project_name]
            service = services.get(scene.issue_component or 'backend-api')

            pipeline = None
            code_change = None
            if scene.deploy_sha and scene.deploy_message:
                pipeline = self._make_pipeline(org, project, scene, scene_time)
                code_change = self._make_code_change(
                    org, project, scene, scene_time, pipeline,
                    author=DEMO_AUTHORS[scene_index % len(DEMO_AUTHORS)],
                )
                # Deployment row so the Deployments panel + service-
                # health map have real data to plot. One deploy per
                # code change; environment matches the scene.
                self._make_deployment(scene, scene_time, pipeline, code_change)

            batch = self._make_batch(
                org, project, scene, scene_time, scene_index,
                pipeline=pipeline,
                code_change=code_change,
            )
            self._make_token_usage(org, batch, scene_time, scene)

            if scene.issue_type:
                issue = self._make_issue(
                    org, project, batch, service, scene, scene_time,
                    code_change=code_change,
                )
                issues_by_component[scene.issue_component] = issue
                # Alert wiring — keep the latest batch per component so
                # the alert-event seed below can link the "triggered_batch"
                # FK to something real.
                if scene.issue_component:
                    batches_by_component[scene.issue_component] = batch
                if scene.issue_severity == 'CRITICAL' and scene.issue_status == 'OPEN':
                    critical_issues.append(issue)

        # Pre-seed three chat sessions on top of the surviving issues —
        # the centerpiece, the memory leak, and the database error.
        self._seed_chat_sessions(org, projects, services, issues_by_component)

        # Notifications on the CRITICAL open issues so the bell icon
        # has an unread badge for a demo visitor to click into.
        self._seed_notifications(org, critical_issues)

        # Back-dated audit trail so Settings → Audit Log isn't blank.
        self._seed_audit_log(org)

        # Alert events (Items #13, #14) — links back to the story-arc
        # batches so the alert list + batch-detail "triggered by" panel
        # both look wired up.
        self._seed_alert_events(org, batches_by_component)

    # ── Builders ───────────────────────────────────────────────────────

    @staticmethod
    def _make_pipeline(
        org: Organisations, project: Project, scene: Scene, scene_time: datetime,
    ) -> Pipeline:
        """Lightweight Pipeline + a single passing build Job.

        We use GitHub Actions as the synthetic CI provider so the demo
        does not require a fake GitlabProject. ``external_project_id``
        keeps Pipeline portable across providers.
        """
        pipeline = Pipeline.objects.create(
            organisation=org,
            pipeline_id=f'gh-{scene.deploy_sha}-{scene.days_ago}',
            cicd_provider='github_actions',
            external_project_id=f'acme/{project.name}',
            status='success',
            branch='main',
            environment=scene.environment,
            provider_metadata={
                'workflow': 'deploy.yml',
                'commit_sha': scene.deploy_sha,
                'message': scene.deploy_message,
            },
        )
        Job.objects.create(
            pipeline=pipeline,
            job_id=f'{scene.deploy_sha}-build',
            name='build-and-test',
            status='success',
            error_summary='',
        )
        return pipeline

    @staticmethod
    def _make_code_change(
        org: Organisations,
        project: Project,
        scene: Scene,
        scene_time: datetime,
        pipeline: Pipeline,
        author: tuple[str, str],
    ) -> CodeChange:
        author_name, author_email = author
        return CodeChange.objects.create(
            organisation=org,
            provider='github',
            project_id=f'acme/{project.name}',
            commit_sha=scene.deploy_sha,
            commit_message=scene.deploy_message,
            author_name=author_name,
            author_email=author_email,
            timestamp=scene_time,
            branch='main',
            pipeline=pipeline,
            files_changed=2,
            additions=18,
            deletions=4,
            diff_summary={
                'files': [
                    {
                        'path': (
                            'backend/payment_webhooks.py'
                            if 'backend' in scene.deploy_message else
                            'frontend/src/components/Checkout.jsx'
                        ),
                        'additions': 18,
                        'deletions': 4,
                    },
                ],
            },
            diff_fetched=True,
        )

    @staticmethod
    def _make_batch(
        org: Organisations,
        project: Project,
        scene: Scene,
        scene_time: datetime,
        scene_index: int,
        pipeline: Pipeline | None = None,
        code_change: 'CodeChange | None' = None,
    ) -> AIAnalyzedBatch:
        triggers = (
            ['error_rate_spike'] if scene.issue_type and not scene.quiet else []
        )
        if scene.deploy_sha:
            triggers.append('deployment_detected')
        # Rich per-batch data so Detail.jsx tabs (Logs, CI/CD Logs,
        # Metrics, Correlations) all have something to render. This is
        # what visitors drill into after seeing a batch on /dash/data.
        pipeline_id_str = str(pipeline.pipeline_id) if pipeline else ''
        logs = _synthetic_logs(scene, scene_time, project.name)
        cicd_logs = _synthetic_cicd_logs(scene, scene_time, pipeline_id_str)
        # Batch 49 wiring — pin each batch to its owning deployment so
        # the composed filter (Batch 54) matches it correctly. Prefer
        # the base per-env deployment for this scene (region='', ns='')
        # since the story arc scenes don't model region/namespace shape.
        deployment = ProjectDeployment.objects.filter(
            project=project,
            environment__name=scene.environment,
            region='',
            namespace='',
        ).first()
        batch = AIAnalyzedBatch.objects.create(
            batch_id=f'demo-{scene_index:02d}-{scene.days_ago}-{scene.environment}',
            timestamp=scene_time,
            project=project,
            organisation=org,
            environment=scene.environment,
            deployment=deployment,
            sentinel_decision=scene.sentinel_decision,
            sentinel_triggers=triggers,
            ai_skipped=(scene.sentinel_decision == 'quiet'),
            issue_count=(1 if scene.issue_type else 0),
            logs_analyzed=len(logs) + len(cicd_logs),
            token_count=(0 if scene.quiet else 1850),
            analysis_text=(
                scene.issue_root_cause if scene.issue_root_cause
                else 'No notable signal in this window.'
            ),
            analyzed_at=scene_time + timedelta(minutes=4),
            model_name=_demo_ai_model(),
            data={
                'environment': scene.environment,
                'logs_count': len(logs),
                'centerpiece': scene.is_centerpiece,
                'logs': logs,
                'cicd_logs': cicd_logs,
                'metrics': _synthetic_metrics(scene, scene_time),
                'correlation_results': _synthetic_correlations(scene),
                # Trace snapshot — same shape as
                # ai_model.trace_context.build_trace_context writes at
                # ingest. Frontend BatchTraces reads this via
                # batch.data.traces (Option A consolidation, Batch 38).
                'traces': _synthetic_traces(scene, scene_time),
                # code_changes snapshot — same shape the production
                # batch pipeline writes. Required for the timeline's
                # unified event stream (deploy lane) + engine-backed
                # causal arrows (Batch 42). Prior code seeded the
                # CodeChange DB row but never mirrored it into batch.data
                # so the deploy lane was silently empty on the demo.
                'code_changes': (
                    [{
                        'sha': code_change.commit_sha,
                        'timestamp': (scene_time - timedelta(minutes=8)).isoformat(),
                        'author': code_change.author_name,
                        'message': scene.deploy_message or '',
                        'branch': ('main' if scene.environment == 'production'
                                   else 'develop'),
                        'stats': {'files': 3, 'additions': 42, 'deletions': 8},
                        'files': [
                            {'path': 'api/payment_webhooks.py', 'diff': ''},
                        ],
                    }] if code_change else []
                ),
            },
        )
        return batch

    @staticmethod
    def _make_token_usage(
        org: Organisations, batch: AIAnalyzedBatch, scene_time: datetime, scene: Scene,
    ) -> None:
        if scene.quiet:
            return  # Skipped batches don't consume tokens.
        # Realistic-ish numbers — keep cost > $0 so the hero widget shows
        # a value rather than $0.
        AITokenUsage.objects.create(
            organisation=org,
            batch=batch,
            model_name=_demo_ai_model(),
            tokens_input=1500,
            tokens_output=350,
            tokens_total=1850,
            cost_usd=Decimal('0.012'),
            usage_type='batch_analysis',
        )

    @staticmethod
    def _make_issue(
        org: Organisations,
        project: Project,
        batch: AIAnalyzedBatch,
        service: ProjectService | None,
        scene: Scene,
        scene_time: datetime,
        code_change: CodeChange | None,
    ) -> Issue:
        # Stable fingerprint so re-running the seed does not violate the
        # partial unique constraint on (fingerprint, project) for OPEN
        # / MUTED issues.
        fp_seed = f'demo-{scene.issue_type}-{scene.issue_component}-{scene.environment}-{scene.days_ago}'
        fingerprint = 'demo:' + hashlib.sha256(fp_seed.encode()).hexdigest()[:24]

        reasoning_text = Issue._serialize_reasoning(scene.issue_reasoning)
        resolved_at = scene_time + timedelta(hours=18) if scene.issue_status == 'RESOLVED' else None
        muted_until = scene_time + timedelta(days=7) if scene.issue_status == 'MUTED' else None

        # Pre-set the correlation fields so the dashboard's correlation
        # insights card has data to show without having to run the
        # correlation engine on synthetic logs.
        linked_commits = []
        if code_change:
            linked_commits = [
                {
                    'sha': code_change.commit_sha,
                    'message': code_change.commit_message[:80],
                    'author': code_change.author_name,
                    'timestamp': code_change.timestamp.isoformat(),
                }
            ]

        issue = Issue.objects.create(
            batch=batch,
            project=project,
            organisation=org,
            issue_type=scene.issue_type,
            scope='SERVICE',
            component=scene.issue_component or '',
            environment=scene.environment,
            severity=scene.issue_severity or 'WARNING',
            description=scene.issue_description,
            root_cause=scene.issue_root_cause,
            recommendation=scene.issue_recommendation,
            reasoning=reasoning_text,
            confidence=scene.issue_confidence,
            fingerprint=fingerprint,
            status=scene.issue_status,
            resolved_at=resolved_at,
            muted_until=muted_until,
            error_class=scene.issue_type,
            error_target=scene.issue_component or '',
            has_commit_correlation=bool(linked_commits),
            linked_commits=linked_commits,
            correlation_confidence='HIGH' if scene.is_centerpiece else 'MEDIUM',
        )
        # Hard-set created_at so the issue dates back to the scene time
        # rather than "now" — Django auto_now_add ignores explicit values
        # on create, so update separately.
        Issue.objects.filter(pk=issue.pk).update(created_at=scene_time)
        issue.refresh_from_db()
        return issue

    # ── Chat sessions ─────────────────────────────────────────────────

    @staticmethod
    def _make_deployment(
        scene: Scene,
        scene_time: datetime,
        pipeline: Pipeline,
        code_change: CodeChange,
    ) -> Deployment:
        """One Deployment per successful build so the Deployments panel
        (and Recent Deployments feed on the dashboard) render real
        rows. `status` follows the scene — critical open issues get
        'failed' so a visitor sees the causal link.
        """
        is_failed = scene.issue_severity == 'CRITICAL' and scene.issue_status == 'OPEN'
        return Deployment.objects.create(
            code_change=code_change,
            pipeline=pipeline,
            environment=scene.environment,
            deployed_at=scene_time,
            status='failed' if is_failed else 'success',
            notes=scene.deploy_message or '',
        )

    def _seed_notifications(self, org: Organisations, critical_issues: list) -> None:
        """Drop one unread notification per open CRITICAL issue so the
        bell icon has an unread badge on load. Also seed one 'digest'
        entry so the "read" tab isn't empty.
        """
        user = User.objects.get(email=DEMO_USER_EMAIL)
        for issue in critical_issues:
            Notification.objects.create(
                user=user,
                subject=f'[CRITICAL] {issue.issue_type} on {issue.component}',
                message=issue.description[:200] if issue.description else '',
                notification_type='critical_issue',
                batch_id=(issue.batch.batch_id if issue.batch else ''),
                issue=issue,
                is_read=False,
            )
        # A read digest so the notification list has both states.
        Notification.objects.create(
            user=user,
            subject='Weekly digest — 3 issues resolved, 2 opened',
            message='Your team resolved the payment-webhook memory leak and the flaky staging test this week. Two new criticals remain open on redis-cache and postgres-primary.',
            notification_type='digest',
            is_read=True,
        )

        # Project subscriptions — subscribe the demo user to both
        # projects so the Notification Preferences page shows real
        # rows instead of an empty state.
        for project in Project.objects.filter(organisation=org):
            ProjectSubscription.objects.update_or_create(
                user=user,
                project=project,
                defaults={
                    'notify_critical': True,
                    'notify_warning': True,
                    'notify_info': False,
                },
            )

        # One escalation rule so Settings → Escalation Rules isn't
        # empty. Applies org-wide for CRITICAL severity.
        EscalationRule.objects.update_or_create(
            organisation=org,
            project=None,
            severity='CRITICAL',
            defaults={
                'level_1_delay_minutes': 15,
                'level_2_delay_minutes': 45,
                'is_active': True,
            },
        )

    def _seed_audit_log(self, org: Organisations) -> None:
        """Back-dated audit entries so Settings → Audit Log has history.
        Purely presentational — nothing here powers real security
        decisions on the demo host.
        """
        user = User.objects.get(email=DEMO_USER_EMAIL)
        now = timezone.now()
        entries = [
            (7, 'TEAM_INVITE', {'target_email': DEMO_AUTHORS[0][1], 'role': 'user'}),
            (5, 'SETTINGS_CHANGE', {'setting': 'notifications.slack_enabled', 'from': False, 'to': True}),
            (4, 'SERVICE_CREATE', {'service': 'backend-api'}),
            (3, 'AI_MODEL_CHANGE', {'from': 'claude-sonnet-5', 'to': _demo_ai_model()}),
            (2, 'SETTINGS_CHANGE', {'setting': 'sentinel.active_mode', 'from': False, 'to': True}),
            (1, 'LOGIN', {}),
            (0, 'LOGIN', {}),
        ]
        for days, action, details in entries:
            entry = AuditLog.objects.create(
                organisation=org,
                user=user,
                action=action,
                details=details,
                ip_address='198.51.100.42',
                user_agent='Mozilla/5.0 (demo)',
            )
            # created_at is auto_now_add — override in a second pass.
            AuditLog.objects.filter(pk=entry.pk).update(
                created_at=now - timedelta(days=days, hours=1),
            )

    def _seed_chat_sessions(
        self,
        org: Organisations,
        projects: dict[str, Project],
        services: dict[str, ProjectService],
        issues_by_component: dict[str, Issue],
    ) -> None:
        user = User.objects.get(email=DEMO_USER_EMAIL)
        scripts = self._chat_scripts(issues_by_component)
        for title, batch_id, project_id, exchanges in scripts:
            session = ChatSession.objects.create(
                chat_id=uuid.uuid4(),
                user=user,
                title=title,
                batch_id=batch_id,
                project_id=str(project_id) if project_id else None,
                is_active=False,  # closed history rather than ongoing
            )
            for question, answer in exchanges:
                ChatMessage.objects.create(
                    chat_session=session,
                    message=question,
                    response=answer,
                    metadata={'demo': True, 'ai_model': _demo_ai_model()},
                )

    @staticmethod
    def _chat_scripts(
        issues_by_component: dict[str, Issue],
    ) -> list[tuple[str, str | None, int | None, list[tuple[str, str]]]]:
        """Return three pre-canned investigations as (title, batch_id,
        project_id, [(question, answer), ...]) tuples."""
        redis_issue = issues_by_component.get('redis-cache')
        backend_leak = issues_by_component.get('backend-api')
        return [
            (
                'Why is Redis refusing connections?',
                redis_issue.batch.batch_id if redis_issue else None,
                redis_issue.project_id if redis_issue else None,
                [
                    (
                        'Why is payment-worker getting connection refused on Redis?',
                        (
                            'The v2.3.3 deploy 4 hours ago shrank the Redis '
                            'connection pool from 50 to 20 ("perf(infra): '
                            'shrink redis pool 50→20 to save memory", '
                            'commit a3f1d8c0). With current production load '
                            'the 20-connection pool saturates within ~4 '
                            'minutes; once exhausted, workers see '
                            'ConnectionRefusedError until a connection is '
                            'released.\n\nConfidence: HIGH — the deploy '
                            'time, the metric anomaly, and the error logs '
                            'all align within a 6-minute window.'
                        ),
                    ),
                    (
                        'Could it be the upstream payment provider instead?',
                        (
                            'No — checked the provider status page (all '
                            'green) and other queues backed by the same '
                            'Redis cluster (session store, analytics) are '
                            'also showing pool exhaustion. The fault is '
                            'inside our own Redis cluster, not upstream.'
                        ),
                    ),
                    (
                        'What\'s the quickest fix?',
                        (
                            'Revert the pool size to 50 (PR #1259, ready '
                            'to merge). Longer term, add a Prometheus '
                            'alert on redis_pool_used > 80 % so this '
                            'fails loud rather than silently degrading '
                            'into a queue backup.'
                        ),
                    ),
                ],
            ),
            (
                'What happened to backend-api memory two days ago?',
                backend_leak.batch.batch_id if backend_leak else None,
                backend_leak.project_id if backend_leak else None,
                [
                    (
                        'Backend memory climbed from 55% to 88% over 3 hours — was it the deploy?',
                        (
                            'Yes. v2.3.2 ("feat(backend): batch payment-webhook '
                            'acks", commit b2c4d8e3) introduced a pandas '
                            'DataFrame in payment_webhooks.py that accumulates '
                            'rows without bound. Under steady webhook traffic '
                            'memory grows linearly until the worker is OOM-killed.'
                        ),
                    ),
                    (
                        'Was this caught by alerting?',
                        (
                            'No — there was no Prometheus rule for backend '
                            'memory at the time. SerOps surfaced it via the '
                            'next scheduled batch because the metric anomaly '
                            'tripped Sentinel\'s z-score threshold even '
                            'without a configured alert. This is exactly the '
                            '"alert-agnostic" detection promise.'
                        ),
                    ),
                ],
            ),
            (
                'Walk me through how SerOps decided on the root cause',
                redis_issue.batch.batch_id if redis_issue else None,
                redis_issue.project_id if redis_issue else None,
                [
                    (
                        'Show me your reasoning for the Redis incident',
                        (
                            'Step 1 — I saw repeated `ConnectionRefusedError` in '
                            'payment-worker logs starting 13:58 UTC.\n\n'
                            'Step 2 — I checked the recent deploys and found '
                            'v2.3.3 landed 4 minutes earlier; the diff shrank '
                            'the Redis pool from 50 to 20.\n\n'
                            'Step 3 — I pulled Redis metrics: redis_pool_used '
                            'hit 100% within 4 minutes of the deploy, exactly '
                            'matching the log onset.\n\n'
                            'Step 4 — I ruled out the upstream payment provider '
                            'because their status page is green and unrelated '
                            'queues sharing the same Redis are also affected.'
                        ),
                    ),
                ],
            ),
        ]
