import os
import logging
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv
from datetime import timedelta


logger = logging.getLogger(__name__)

load_dotenv ()

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

# Allow Celery to run as root in Docker development environment
# In production, use a non-root user instead
os.environ.setdefault('C_FORCE_ROOT', '1')

app = Celery('api')

BASE_TICK_RATE = int(os.getenv('BATCH_SCHEDULER_TICK_RATE', 1))

logger.info(f"[CONFIG] Batch scheduler tick rate: {BASE_TICK_RATE} minute(s)")


app.config_from_object('django.conf:settings', namespace='CELERY')

# Phase 2: Dynamic worker concurrency based on CPU cores
# Formula: (CPU cores * 2) or minimum 6 for parallel batch processing
worker_concurrency = max(6, os.cpu_count() * 2 if os.cpu_count() else 6)
logger.info(f"[CONFIG] Celery worker concurrency set to {worker_concurrency}")

# Celery worker configuration
app.conf.update(
    broker_connection_retry_on_startup=True,
    worker_pool_restarts=True,
    broker_connection_max_retries=None,
    worker_cancel_long_running_tasks_on_connection_loss=False,
    task_track_started=True,
    worker_concurrency=worker_concurrency,  # Dynamic: 6-16 workers
    worker_prefetch_multiplier=2,  # Fetch 2 tasks per worker for efficiency
    worker_max_tasks_per_child=1000,  # Restart workers after 1000 tasks (prevent memory leaks)
    task_time_limit=600,
    broker_heartbeat=0,
    task_acks_late=True,  # Only acknowledge tasks after completion
    task_reject_on_worker_lost=True,  # Requeue tasks if worker is lost
)

app.autodiscover_tasks()

# Phase 2: Task routing and priority queues
# Route tasks to appropriate queues based on duration and priority
app.conf.task_routes = {
    # High priority: Quick batch operations (< 30 seconds)
    'Data.tasks.create_log_batch': {'queue': 'high_priority'},
    'Data.tasks.create_log_batch_with_project_name': {'queue': 'high_priority'},

    # Normal priority: Standard processing (30s - 5min)
    'Data.tasks.create_batches_for_all_projects': {'queue': 'normal'},
    'Data.tasks.run_auto_retention_cleanup': {'queue': 'normal'},
    'Data.tasks.trim_raw_metric_payloads': {'queue': 'background'},
    'providers.tasks.sync_recent_deployments': {'queue': 'normal'},

    # Background: Long-running AI tasks (5min+)
    'ai_model.tasks.analyze_batch': {'queue': 'background'},
    'Data.tasks.reset_demo_org': {'queue': 'background'},

    # Notifications: Medium priority
    'notifications.tasks.check_escalations': {'queue': 'normal'},
    'notifications.tasks.process_digest_notifications': {'queue': 'background'},
    'notifications.tasks.retry_failed_notifications': {'queue': 'normal'},
    'notifications.tasks.cleanup_old_notifications': {'queue': 'background'},
}

# Configure queue priorities (higher = more important)
app.conf.task_queue_max_priority = 10
app.conf.task_default_priority = 5

# Task time limits (safety guards)
app.conf.task_time_limit = 60 * 30  # 30 minutes hard limit
app.conf.task_soft_time_limit = 60 * 25  # 25 minutes soft limit

logger.info(f"[CONFIG] Task routing configured with 3 queues: high_priority, normal, background")

app.conf.beat_schedule = {
    'create-combined-batch': {
        'task': 'Data.tasks.create_batches_for_all_projects',
        'schedule': timedelta(minutes=BASE_TICK_RATE),
        'options': {
            'queue': 'normal',
            'priority': 7,  # High but not highest
        }
    },
    'auto-retention-cleanup': {
        'task': 'Data.tasks.run_auto_retention_cleanup',
        'schedule': timedelta(hours=1),
        'options': {
            'queue': 'background',
            'priority': 3,
        }
    },
    # Sheds the raw metric points — 93% of a batch's payload, and chart-only —
    # from batches past raw_metrics_retention_days, keeping the analysis and the
    # metric summary. Daily is often enough for something that only reclaims
    # storage; hourly would rewrite rows for no benefit.
    'trim-raw-metric-payloads': {
        'task': 'Data.tasks.trim_raw_metric_payloads',
        'schedule': timedelta(hours=24),
        'options': {
            'queue': 'background',
            'priority': 2,
        }
    },
    'auto-deployment-sync': {
        'task': 'providers.tasks.sync_recent_deployments',
        'schedule': timedelta(minutes=10),
        'kwargs': {'hours': 2},
        'options': {
            'queue': 'normal',
            'priority': 6,
        }
    },
    # === NOTIFICATION SYSTEM TASKS ===
    # Check for unacknowledged critical issues and escalate
    'notification-escalation-check': {
        'task': 'notifications.tasks.check_escalations',
        'schedule': timedelta(minutes=5),
        'options': {
            'queue': 'normal',
            'priority': 8,  # High priority for escalations
        }
    },
    # Process queued digest notifications
    'notification-digest-processing': {
        'task': 'notifications.tasks.process_digest_notifications',
        'schedule': timedelta(hours=1),
        'options': {
            'queue': 'background',
            'priority': 4,
        }
    },
    # Retry failed email notifications
    'notification-retry-failed': {
        'task': 'notifications.tasks.retry_failed_notifications',
        'schedule': timedelta(minutes=15),
        'options': {
            'queue': 'normal',
            'priority': 6,
        }
    },
    # Cleanup old notification queue entries
    'notification-cleanup': {
        'task': 'notifications.tasks.cleanup_old_notifications',
        'schedule': timedelta(hours=24),  # Once per day
        'options': {
            'queue': 'background',
            'priority': 2,
        }
    },
    # === DEMO ORG MAINTENANCE ===
    # Rebuild the public Acme Cloud demo nightly so visitor mutations
    # never drift the story. No-op on deployments without a demo org.
    'demo-org-nightly-reset': {
        'task': 'Data.tasks.reset_demo_org',
        'schedule': crontab(hour=2, minute=0),  # 02:00 UTC
        'options': {
            'queue': 'background',
            'priority': 1,
        }
    },
}

# A periodic tick still queued when the next one is due is stale: the next
# tick does the same job. Expiring it keeps a worker outage (or, before the
# Helm chart consumed every queue, a queue nobody read) from replaying hours
# of ticks at once when consumption resumes.
for _entry in app.conf.beat_schedule.values():
    if isinstance(_entry['schedule'], timedelta):
        _entry.setdefault('options', {}).setdefault('expires', _entry['schedule'].total_seconds())

@app.task(bind=True)
def debug_task(self):
    logger.debug(f'Request: {self.request!r}')