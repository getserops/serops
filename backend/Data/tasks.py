from collections import defaultdict
import json
import os
from celery import shared_task
import logging
from django.utils import timezone
from integrations.registry import IntegrationRegistry
from integrations.schemas import LogEntry, LogQuery
from .models import (
    AIAnalyzedBatch,
    RetentionPolicy, AuditLog
)
from django.conf import settings
from ai_model.tasks import analyze_batch
from datetime import datetime
from .serializers import serialize_metrics
from Projects.models import Project
from .audit import log_batch_delete

# ── Phase 4: Re-exported from integrations/ingestion.py ──
from integrations.ingestion import (  # noqa: F401
    ENVIRONMENT_ALIASES,
    is_log_matching_environment,
    deduplicate_logs,
    filter_unique_logs,
    filter_unique_logs_for_project,
    create_elasticsearch_query,
    get_latest_batch_timestamp,
    get_last_processed_log_timestamp,
    get_scheduled_window_start,
)

# ── Phase 4: Re-exported from integrations/metrics_processing.py ──
from integrations.metrics_processing import (  # noqa: F401
    fetch_metrics_with_provider as _fetch_metrics_with_provider,
    calculate_memory_usage,
    calculate_cpu_usage,
    preprocess_metrics_for_ai,
    clean_json,
)



logger = logging.getLogger(__name__)
elastic_index = getattr(settings, 'ELASTICSEARCH_DEFAULT_INDEX', 'logs-*')
Metrics_interval = int(os.getenv('BATCH_GENERATION_INTERVAL', 5))


# Toggle to enable/disable metrics collection
METRICS_ENABLED = getattr(settings, 'METRICS_ENABLED', os.getenv('METRICS_ENABLED', 'false').lower() == 'true')


# Default lock TTL — a bit longer than the batch interval to prevent overlap
_TASK_LOCK_TTL = int(os.getenv('BATCH_TASK_LOCK_TTL', Metrics_interval * 60 + 120))  # seconds


def _acquire_task_lock(lock_key, ttl=None, interval_minutes=None):
    """
    Acquire a distributed lock via Django cache (Redis-backed).
    Returns True if acquired, False if another instance holds it.
    """
    from django.core.cache import cache
    if ttl is None:
        ttl = (interval_minutes or Metrics_interval) * 60 + 120
    # cache.add returns True only if the key didn't exist (atomic set-if-not-exists)
    return cache.add(lock_key, True, timeout=ttl)


def _release_task_lock(lock_key):
    """Release a distributed lock."""
    from django.core.cache import cache
    cache.delete(lock_key)



@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    priority=8,  # Phase 2: High priority (scale 0-10)
    queue='high_priority'
)
def create_log_batch(self):
    logger.info("Starting create_log_batch task")
    lock_key = 'task_lock:create_log_batch'
    if not _acquire_task_lock(lock_key):
        logger.info("create_log_batch already running, skipping this execution")
        return "Skipped: another instance is running"
    try:
        current_time = timezone.now()
        logger.info(f"Current time: {current_time.isoformat()}")
        
        last_batch_time = get_latest_batch_timestamp()
        logger.info(f"Last batch time: {last_batch_time.isoformat() if last_batch_time else 'None'}")
        
        # Determine batch start time
        if last_batch_time:
            batch_start_time = last_batch_time
        else:
            batch_start_time = current_time - timezone.timedelta(minutes=Metrics_interval)
        batch_end_time = current_time
        logger.info(f"Batch window: {batch_start_time.isoformat()} to {batch_end_time.isoformat()}")
        
        time_window = batch_start_time

        # Create query with current timestamp
        query = create_elasticsearch_query(last_batch_time)
        logger.info(f"Elasticsearch query: {query}")
        
        # Placeholder for environment, as create_log_batch doesn't have it directly
        environment = None 

        # 1. Fetch Metrics (existing logic, but ensure start/end times are defined)
        # These variables are usually defined in the metrics fetching block later.
        # For now, we'll define them here to satisfy the _fetch_metrics_with_provider call.
        # This part of the diff seems misplaced, so I'm re-aligning it with the original structure.
        # The original code fetches metrics later. I'll keep the metrics fetching in its original place.
        
        # 2. Fetch Logs via Provider
        logs = []
        try:
            # Use default organization since we don't have a project context
            # Note: callers with project context should use create_log_batch_for_project instead
            # This task has no project context — pass None to get the default provider
            try:
                provider = IntegrationRegistry.get_log_provider_for_org(None)
            except ValueError:
                logger.warning("No global log integration configured. Skipping global batch creation.")
                return "No global log integration configured"
            
            # Build provider-agnostic query using LogQuery DTO
            log_query = LogQuery(
                time_range=(batch_start_time, batch_end_time) if last_batch_time else None,
                severity=['ERROR', 'WARNING', 'CRITICAL'],
                category='cicd',
                event_type='cicd_job_failure',
            )
            
            # LogProvider.search() transparently translates LogQuery to native format
            log_entries = provider.search(None, log_query)
            
            # Convert to legacy dict format for compatibility with dedup and AI logic
            # Keep LogEntry objects for processing
            logs = log_entries
            
        except Exception as e:
            logger.error(f"Error searching logs: {e}")
            logs = []

        # 3. Filter by Environment logic (legacy)
        # Since the provider search didn't strictly filter by environment (only time),
        # we filter manually here to match original logic
        # For create_log_batch, environment is usually 'production' or auto-detected later.
        # If environment is None, is_log_matching_environment should return True.
        logs = [log for log in logs if is_log_matching_environment(log, environment)]

        # 4. Filter unique logs (no org context in global batch — pass None)
        window_start = last_batch_time if last_batch_time else (timezone.now() - timezone.timedelta(minutes=5))
        unique_hits = filter_unique_logs(logs, window_start, organisation=None)
        
        logger.info(f"After filtering unique logs: {len(unique_hits)} logs")

        # Debug the in_batch_window function
        def in_batch_window(log):
            if hasattr(log, 'timestamp'):
                ts = log.timestamp
                ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                log_time = ts if isinstance(ts, datetime) else datetime.fromisoformat(ts.replace('Z', '+00:00'))
            else:
                ts_str = log.get('_source', {}).get('@timestamp')
                if not ts_str:
                    logger.warning(f"Log missing timestamp: {log}")
                    return False
                try:
                    log_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                except Exception as e:
                    logger.error(f"Error parsing timestamp {ts_str}: {str(e)}")
                    return False
            
            result = batch_start_time <= log_time <= batch_end_time
            if not result:
                logger.debug(f"Log outside batch window - ts: {ts_str}, log_time: {log_time}, " 
                            f"start: {batch_start_time}, end: {batch_end_time}")
            return result

        logs_in_window = [log for log in unique_hits if in_batch_window(log)]
        logger.info(f"Logs in batch window: {len(logs_in_window)}")
        
        # ADD THIS DEBUG SECTION (without project_name):
        logger.info("DEBUG - Analyzing log severity levels:")
        severity_counts = {}
        for log in logs_in_window:
            source = log.get('_source', {})
            level = source.get('log_level', source.get('level', 'UNKNOWN')).upper()
            severity_counts[level] = severity_counts.get(level, 0) + 1
        logger.info(f"Severity breakdown: {severity_counts}")

        # Log sample messages to understand what's being filtered
        for i, log in enumerate(logs_in_window[:3]):
            source = log.get('_source', {})
            logger.info(f"Sample log {i}: level={source.get('log_level')}, message={source.get('message', '')[:100] if source.get('message') else 'No message'}")

        # Exclude info-level and debug-level logs from batch creation
        def is_important_log(log):
            if hasattr(log, 'message'):
                message = log.message
                level = log.level.upper()
                alt_level = log.labels.get('level', '').upper()
            else:
                source = log.get('_source', {})
                message = source.get('message', '')
                level = source.get('log_level', '').upper()
                alt_level = source.get('level', '').upper()
            
            # Check both fields for important severity levels
            # Added INFO to ensure we capture operational logs even if no errors occur
            if level in ['INFO', 'WARNING', 'ERROR', 'CRITICAL'] or alt_level in ['INFO', 'WARNING', 'ERROR', 'CRITICAL']:
                return True
                
            # If not, try to extract severity from message content
            if ' ERROR ' in message.upper() or ' CRITICAL ' in message.upper() or ' WARNING ' in message.upper() or 'INVALID USER' in message.upper() or 'AUTHENTICATION FAILURE' in message.upper() or 'FAILED' in message.upper():
                return True
                
            # Additionally check for security related messages
            if 'sshd' in message and ('invalid user' in message.lower() or 'authentication failure' in message.lower()):
                return True
                
            return False
        
        filtered_hits = [log for log in logs_in_window if is_important_log(log)]
        logger.info(f"Important logs: {len(filtered_hits)}")

        # ADD THIS:
        if len(filtered_hits) == 0 and len(logs_in_window) > 0:
            logger.warning(f"All {len(logs_in_window)} logs were filtered out as unimportant!")
        
        # Apply log deduplication to reduce AI token costs
        original_count = len(filtered_hits)
        filtered_hits = deduplicate_logs(filtered_hits)
        logger.info(f"After deduplication: {len(filtered_hits)} unique patterns (from {original_count} logs)")
        
        # FINAL STEP: Convert LogEntry objects to dicts for JSON storage
        # This is where we bridge back to the legacy format required for AIAnalyzedBatch.data
        filtered_hits = [
            log.to_legacy_dict() if hasattr(log, 'to_legacy_dict') else log 
            for log in filtered_hits
        ]
        
        # Fetch metrics for the exact batch window
        if not METRICS_ENABLED:
            # `metrics` must be bound on BOTH branches. It is read
            # unconditionally further down (`preprocess_metrics_for_ai(metrics)
            # if metrics else {}`), so leaving it unassigned here raised
            # UnboundLocalError and took the whole batch down — Celery then
            # retried it to exhaustion. METRICS_ENABLED defaults to FALSE
            # (see the getattr/getenv above), so this was the default path:
            # a Helm-deployed SerOps could not create a single batch, while
            # docker-compose installs were fine only because .env sets it true.
            metrics = {}
            serialized_metrics = {}
            logger.info("Metrics collection disabled (METRICS_ENABLED=False). Skipping metrics fetch.")
        else:
            try:
                metrics = {}
                # Metrics_interval, the same window this task's batch uses.
                # `effective_interval` belongs to create_log_batch_with_project_name
                # and was never bound here, so with metrics enabled this raised
                # NameError. Found by ruff F821 once CI selected that rule.
                metrics_start_time = current_time - timezone.timedelta(minutes=Metrics_interval)
                metrics_end_time = current_time

                logger.info(f"Fetching metrics with timestamp between {metrics_start_time} and {metrics_end_time}")
                
                 # Use helper to fetch metrics via provider
                metrics = _fetch_metrics_with_provider(
                    metrics_start_time, 
                    metrics_end_time
                )
                
                # Log the number of metrics found in each category
                logger.info(f"Found metrics: total={len(metrics['memory_total'])}, free={len(metrics['memory_free'])}, "
                           f"available={len(metrics['memory_available'])}, cpu={len(metrics['cpu'])}")

                # Calculate memory usage percentage
                memory_usage = calculate_memory_usage(metrics)
                metrics['memory_usage_percent'] = memory_usage

                # Calculate CPU usage percentage (skip if pre-computed by provider)
                if 'cpu_usage_percent' not in metrics:
                    cpu_usage = calculate_cpu_usage(metrics.get('cpu', []))
                    metrics['cpu_usage_percent'] = cpu_usage

                # Use the imported serialize_metrics function - ensure it handles lists properly
                serialized_metrics = serialize_metrics(metrics)

                # Verify that serialized_metrics is a dictionary before proceeding
                if not isinstance(serialized_metrics, dict):
                    logger.error(f"serialized_metrics is not a dictionary: {type(serialized_metrics)}")
                    serialized_metrics = {}  # Reset to empty dict to avoid errors
                
                logger.info(f"Metrics count: {sum(len(m) for m in serialized_metrics.values() if isinstance(m, list))}")

            except Exception as e:
                logger.error(f"Error fetching metrics: {str(e)}", exc_info=True)
                serialized_metrics = {}

        # Check if both logs and metrics are empty
        metrics_count = sum(len(m) for m in serialized_metrics.values() if isinstance(m, list)) if serialized_metrics else 0
        if not filtered_hits and metrics_count == 0:
            logger.info("No new unique logs and no new metrics found. Batch will not be created.")
            return "No new logs or metrics found to create batch"

        # Prepare data and clean it before saving
        # Create AI-friendly metrics summary (compact version for analysis)
        metrics_summary = preprocess_metrics_for_ai(metrics) if metrics else {}
        
        # Fetch recent code changes with 2-hour lookback
        # Note: create_log_batch doesn't have project context, so we skip code changes
        # Code changes correlation is handled in create_log_batch_with_project_name
        code_changes_data = []
        
        batch_data = {
            'logs': filtered_hits,
            'metrics': serialized_metrics,  # Raw metrics for visualization
            'metrics_summary': metrics_summary,  # Compact summary for AI analysis
            'code_changes': code_changes_data,  # Empty for this function
            'statistics': {
                'total_logs': len(filtered_hits),
                'total_metrics': metrics_count,
                'total_code_changes': len(code_changes_data),
                'time_range': {
                    'start': batch_start_time.isoformat(),
                    'end': batch_end_time.isoformat()
                }
            },
            # No 'ai_analysis' seed: nothing ever wrote to that key, and the
            # readers that looked there returned empty for every batch. The
            # analysis lands on data['analysis_result'] via save_analysis.
        }
        cleaned_data = clean_json(batch_data)

        # Création du batch
        batch = AIAnalyzedBatch.objects.create(
            batch_id=AIAnalyzedBatch.generate_batch_id(),
            timestamp=current_time,
            logs_analyzed=len(filtered_hits),
            indices_covered=[elastic_index],
            data=cleaned_data
        )

        # Calculate and update token count
        batch.calculate_tokens_from_logs()


        # Trigger AI analysis directly, don't rely on chained tasks
        try:
            # Skip preprocessing to avoid race conditions
            analyze_batch.delay(batch.batch_id)
            logger.info(f"Directly queued analysis for batch {batch.batch_id}")
        except Exception as e:
            logger.error(f"Failed to queue analysis: {str(e)}")
    
        logger.info(f"Successfully created batch {batch.batch_id} with {len(filtered_hits)} new logs and {batch.token_count} tokens")
        return f"Successfully created batch {batch.batch_id}"

    except Exception as e:
        logger.error(f"Error creating log batch (attempt {self.request.retries + 1}/3): {str(e)}", exc_info=True)
        # Retry with exponential backoff (10s, 20s, 40s)
        raise self.retry(exc=e, countdown=10 * (2 ** self.request.retries))
    finally:
        _release_task_lock(lock_key)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    priority=8,  # Phase 2: High priority (scale 0-10)
    queue='high_priority'
)
def create_log_batch_with_project_name(self, index_name=None, project_name=None, project=None, environment=None, deployment=None, interval_minutes=None, window_start_iso=None, window_end_iso=None, trigger=AIAnalyzedBatch.TRIGGER_SCHEDULED, batch_id=None, investigation_id=None):
    """
    Create a log batch scoped to a specific project + environment (+ deployment).

    Args:
        index_name: Elasticsearch index/indices to search
        project_name: Project name for batch ID
        project: Project model instance OR project ID (int) for Celery serialization
        environment: ProjectEnvironment instance OR environment ID (int)
        deployment: ProjectDeployment instance OR deployment ID (int) — Batch 49.
                    When provided, the batch's ``deployment`` FK is set and
                    integration lookup uses full-scope match-scoring
                    (cluster + env + region + namespace). Backward-compat:
                    pre-Batch 49 callers passing only ``environment`` still
                    work, but their batches won't benefit from region /
                    namespace-scoped integration routing.
        interval_minutes: Per-org batch generation interval override (in minutes).
        window_start_iso, window_end_iso: Q5-1. Alert-triggered analyses
            pass a tight window centered on the alert's received_at
            timestamp so a 30-second incident isn't analysed against 15
            minutes of unrelated noise. Both must be ISO-8601 strings
            (Celery has to serialise the args; datetimes travel poorly
            across the broker on some brokers). When either is None the
            scheduled-batch default kicks in: pick up from the last
            scheduled batch's end, or fall back to ``current_time - interval``.
        trigger: what asked for this batch (scheduled, alert, manual).
        batch_id: use this id instead of generating one, so the caller can
            find exactly the batch it created.
        investigation_id: run an Investigation. Scope and window come from
            it; the run skips Sentinel and dedup history, uses its own lock,
            never retries, and records its outcome on the investigation.
    """
    from Projects.models import Project, ProjectEnvironment, ProjectDeployment

    # Convert IDs to model instances if needed (for Celery task serialization)
    if isinstance(project, int):
        try:
            project = Project.objects.get(id=project)
        except Project.DoesNotExist:
            logger.error(f"Project with ID {project} not found")
            return f"Error: Project ID {project} not found"

    if isinstance(environment, int):
        try:
            environment = ProjectEnvironment.objects.get(id=environment)
        except ProjectEnvironment.DoesNotExist:
            logger.error(f"Environment with ID {environment} not found")
            return f"Error: Environment ID {environment} not found"

    if isinstance(deployment, int):
        try:
            deployment = ProjectDeployment.objects.select_related(
                'environment', 'cluster',
            ).get(id=deployment)
        except ProjectDeployment.DoesNotExist:
            logger.warning(
                f"Deployment ID {deployment} not found — falling back to "
                f"env-only batch routing."
            )
            deployment = None

    investigation = None
    if investigation_id is not None:
        from Data.models import Investigation
        investigation = (Investigation.objects
                         .select_related('project__organisation', 'environment', 'deployment')
                         .filter(pk=investigation_id).first())
        if investigation is None:
            logger.error(f"Investigation {investigation_id} not found")
            return {'status': 'error', 'reason': 'investigation_not_found'}
        trigger = AIAnalyzedBatch.TRIGGER_MANUAL
        project = investigation.project
        project_name = project.name
        environment = investigation.environment
        deployment = investigation.deployment
        window_start_iso = investigation.window_start.isoformat()
        window_end_iso = investigation.window_end.isoformat()
    manual = trigger == AIAnalyzedBatch.TRIGGER_MANUAL

    # The batch belongs to the project the caller passed. It used to be
    # looked up again by name across every organisation, and project names
    # are only unique within one, so two organisations with an "api"
    # project could each receive the other's batches.
    if project is None:
        logger.error(f"create_log_batch_with_project_name called without a project ({project_name!r})")
        return "Error: a project is required"

    effective_interval = interval_minutes or Metrics_interval

    logger.info(
        f"Starting create_log_batch with project: {project_name}, "
        f"deployment: {deployment.name if deployment else 'none'}, "
        f"environment: {environment.name if environment else 'auto-detect'}, "
        f"interval: {effective_interval}m"
    )
    # Per-project+env lock to prevent overlapping runs for the same scope.
    # Deployment id included in the lock key so distinct deployments of the
    # same project don't serialize each other (multi-region shops with 3
    # deployments should get 3 concurrent lock slots, not 1).
    env_suffix = f":{environment.id}" if environment else ""
    dep_suffix = f":d{deployment.id}" if deployment else ""
    project_id = project.id if hasattr(project, 'id') else project
    lock_key = f"task_lock:batch_project:{project_id}{env_suffix}{dep_suffix}"
    if investigation is not None:
        # Its own lock: sharing the scheduler's would silently drop the run
        # whenever a scheduled batch for the same scope was in flight.
        lock_key = f"task_lock:investigation:{investigation.pk}"
    if not _acquire_task_lock(lock_key, interval_minutes=effective_interval):
        logger.info(f"Batch task for project {project_name} already running, skipping")
        return f"Skipped: another instance for project {project_name} is running"
    try:
        current_time = timezone.now()
        if investigation is not None:
            investigation.status = investigation.STATUS_COLLECTING
            investigation.started_at = current_time
            investigation.save(update_fields=['status', 'started_at'])

        # Use the provided project name or extract from index
        if not project_name and index_name:
            if "ci_cd-logs-project-" in index_name:
                project_name = index_name.replace("ci_cd-logs-project-", "")
            elif "system-" in index_name:
                project_name = f"system-{index_name.replace('system-', '')}"
            else:
                project_name = index_name
        
        # Generate batch ID with project name
        if batch_id:
            pass
        elif project_name:
            project_prefix = project_name.strip().replace(' ', '-').replace('_', '-').lower()
            import uuid
            unique_suffix = str(uuid.uuid4())[:4]
            batch_id = f"{project_prefix}-batch-{timezone.now().strftime('%Y%m%d%H%M%S')}-{unique_suffix}"
            logger.info(f"Using combined batch ID: '{batch_id}'")
        else:
            batch_id = AIAnalyzedBatch.generate_batch_id()
            logger.info(f"Using standard batch ID: '{batch_id}'")

        # Q5-1: alert-triggered callers pass a tight window around
        # ``event.received_at`` so a short incident doesn't get diluted
        # against 15 minutes of unrelated logs. Scheduled callers pass
        # neither and get the historical "since the last batch" window.
        override_active = bool(window_start_iso and window_end_iso)
        last_batch_time = None
        if override_active:
            try:
                _iso_start = window_start_iso.replace('Z', '+00:00')
                _iso_end = window_end_iso.replace('Z', '+00:00')
                batch_start_time = datetime.fromisoformat(_iso_start)
                batch_end_time = datetime.fromisoformat(_iso_end)
                if batch_start_time.tzinfo is None:
                    batch_start_time = timezone.make_aware(
                        batch_start_time, timezone.utc,
                    )
                if batch_end_time.tzinfo is None:
                    batch_end_time = timezone.make_aware(
                        batch_end_time, timezone.utc,
                    )
                # Force the downstream query paths to use the explicit
                # window (some branches key off ``last_batch_time`` for
                # "how to filter").
                last_batch_time = batch_start_time
                logger.info(
                    f"Batch window (alert-triggered override) for {project_name}: "
                    f"{batch_start_time.isoformat()} to {batch_end_time.isoformat()}"
                )
            except (TypeError, ValueError) as _win_exc:
                logger.warning(
                    f"create_log_batch: bad window override "
                    f"start={window_start_iso!r} end={window_end_iso!r} — "
                    f"falling back to scheduled window: {_win_exc}"
                )
                override_active = False

        if not override_active:
            # Get the last batch timestamp FOR THIS SPECIFIC PROJECT
            last_batch_time = get_scheduled_window_start(project, environment, deployment)
            logger.info(f"Last batch time for project {project_name}: {last_batch_time.isoformat() if last_batch_time else 'None'}")

            # Determine batch start time
            if last_batch_time:
                batch_start_time = last_batch_time
            else:
                batch_start_time = current_time - timezone.timedelta(minutes=effective_interval)
            batch_end_time = current_time
            logger.info(f"Batch window for {project_name}: {batch_start_time.isoformat()} to {batch_end_time.isoformat()}")

        time_window = batch_start_time

        # Create query with current timestamp
        # 3. Fetch logs via Provider
        logs = []
        try:
            # Item #17 / Q1.4: prefer the cluster-scoped integration
            # when the project is assigned to a cluster. Falls through
            # to unscoped (backwards-compat for single-cluster installs).
            _org = project.organisation if project else None
            _cluster = getattr(project, 'cluster', None) if project else None
            provider = IntegrationRegistry.get_log_provider_for_org(
                _org, cluster=_cluster,
            )
            
            # Build provider-agnostic query using LogQuery DTO.
            # ``project`` MUST be set — without it, adapters that use
            # LogQL / label-based selectors (Loki) would produce an
            # empty stream selector and get 400 back. Also protects
            # against multi-tenant leak in shared Loki setups where the
            # only tenant boundary in the query would be the org label.
            log_query = LogQuery(
                time_range=(batch_start_time, batch_end_time) if last_batch_time else None,
                severity=['ERROR', 'WARNING', 'CRITICAL'],
                environment=environment.name if environment else None,
                project=project_name,
            )

            # Get index pattern — prefer caller-provided index_name (already resolved by scheduler)
            if index_name:
                index_pattern = index_name
            else:
                indices = provider.get_indices(project)
                index_pattern = ','.join(indices) if indices else None
            
            # Execute search — LogQuery is translated by the adapter
            log_entries = provider.search(index_pattern, log_query)
            
            logs = log_entries
            
        except Exception as e:
            logger.error(f"Error searching logs for project {project_name}: {e}")
            logs = []      
        
        # Add timestamp debugging for first few log entries
        for i, log_entry in enumerate(logs[:3]):
            if hasattr(log_entry, 'timestamp'):
                ts = log_entry.timestamp
                source_index = log_entry.labels.get('_index', '') if hasattr(log_entry, 'labels') else ''
            else:
                ts = log_entry.get('_source', {}).get('@timestamp')
                source_index = log_entry.get('_index', '')
            logger.info(f"Project {project_name} - Hit {i} timestamp: {ts}, index: {source_index}")

        # Filter unique logs with timestamps FOR THIS PROJECT
        # Pass organisation to ensure multi-tenant isolation in dedup queries
        org = project.organisation if project else None
        unique_hits = filter_unique_logs_for_project(
            logs, time_window, project_name, organisation=org, history=not manual,
        )
        logger.info(f"After filtering unique logs for project {project_name}: {len(unique_hits)} logs")

        # Debug the in_batch_window function
        def in_batch_window(log):
            if hasattr(log, 'timestamp'):
                ts = log.timestamp
                ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
                log_time = ts if isinstance(ts, datetime) else datetime.fromisoformat(ts.replace('Z', '+00:00'))
            else:
                ts_str = log.get('_source', {}).get('@timestamp')
                if not ts_str:
                    logger.warning(f"Log missing timestamp: {log}")
                    return False
                try:
                    log_time = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
                except Exception as e:
                    logger.error(f"Error parsing timestamp {ts_str}: {str(e)}")
                    return False

            result = batch_start_time <= log_time <= batch_end_time
            if not result:
                logger.debug(f"Log outside batch window for {project_name} - ts: {ts_str}, log_time: {log_time}, " 
                            f"start: {batch_start_time}, end: {batch_end_time}")
            return result

        logs_in_window = [log for log in unique_hits if in_batch_window(log)]
        logger.info(f"Logs in batch window for project {project_name}: {len(logs_in_window)}")
        
        # ADD THIS DEBUG SECTION:
        logger.info(f"DEBUG - Analyzing log severity levels for project {project_name}:")
        severity_counts = {}
        for log in logs_in_window:
            if hasattr(log, 'level'):
                level = (log.level or 'UNKNOWN').upper()
            else:
                source = log.get('_source', {})
                level = source.get('log_level', source.get('level', 'UNKNOWN')).upper()
            severity_counts[level] = severity_counts.get(level, 0) + 1
        logger.info(f"Severity breakdown: {severity_counts}")

        # Log sample messages to understand what's being filtered
        for i, log in enumerate(logs_in_window[:3]):
            if hasattr(log, 'message'):
                logger.info(f"Sample log {i}: level={getattr(log, 'level', '?')}, message={log.message[:100]}")
            else:
                source = log.get('_source', {})
                logger.info(f"Sample log {i}: level={source.get('log_level')}, message={source.get('message', '')[:100]}")

        # Exclude info-level and debug-level logs from batch creation
        def is_important_log(log):
            if hasattr(log, 'message'):
                message = log.message or ''
                level = (log.level or '').upper()
            else:
                source = log.get('_source', {})
                message = source.get('message', '')
                level = source.get('log_level', source.get('level', '')).upper()

            if level in ['WARNING', 'WARN', 'ERROR', 'CRITICAL', 'ERR', 'FATAL']:
                return True

            # Try to extract severity from message content
            msg_upper = message.upper()
            if ' ERROR ' in msg_upper or ' CRITICAL ' in msg_upper or ' WARNING ' in msg_upper or 'INVALID USER' in msg_upper or 'AUTHENTICATION FAILURE' in msg_upper or 'FAILED' in msg_upper:
                return True

            # Additionally check for security related messages
            if 'sshd' in message and ('invalid user' in message.lower() or 'authentication failure' in message.lower()):
                return True

            return False
        
        filtered_hits = [log for log in logs_in_window if is_important_log(log)]
        
        # USE ALL LOGS WITHOUT FILTERING
        # filtered_hits = logs_in_window
        logger.info(f"Filtered to {len(filtered_hits)} important logs for project {project_name} (out of {len(logs_in_window)})")

        # === SERVICE-LEVEL FILTERING (STRICT MODE) ===
        # Only include logs from registered services
        logger.info(f"DEBUG: project object = {project}, project_name = {project_name}")
        if project:
            from Projects.models import ProjectService
            services = ProjectService.objects.filter(project=project)
            registered_service_names = set()
            for s in services:
                if s.name:
                    registered_service_names.add(s.name.lower())
            
            logger.info(f"DEBUG: Registered services = {registered_service_names}")
            
            if registered_service_names:
                logger.info(f"Project '{project_name}' has {len(registered_service_names)} registered services: {registered_service_names}")
                
                def is_from_registered_service(log):
                    if hasattr(log, 'service'):
                         service_name = log.service.lower()
                    else:
                         source = log.get('_source', {})
                         service_name = source.get('service_name', '').lower()
                    return service_name in registered_service_names
                
                pre_filter_count = len(filtered_hits)
                filtered_hits = [log for log in filtered_hits if is_from_registered_service(log)]
                logger.info(f"Service filter: {pre_filter_count} → {len(filtered_hits)} logs (kept only registered services)")
                if investigation is not None and investigation.services:
                    registered_service_names &= {name.lower() for name in investigation.services}
                    filtered_hits = [log for log in filtered_hits if is_from_registered_service(log)]
                    logger.info(f"Investigation service scope {sorted(registered_service_names)}: {len(filtered_hits)} logs")
            else:
                # STRICT MODE: No services = no logs
                logger.warning(f"Project '{project_name}' has no registered services. No logs will be included (strict mode).")
                filtered_hits = []
        
        # Apply log deduplication to reduce AI token costs
        original_count = len(filtered_hits)
        filtered_hits = deduplicate_logs(filtered_hits)
        logger.info(f"After deduplication: {len(filtered_hits)} unique patterns (from {original_count} logs)")
        
        # === DETERMINE BATCH ENVIRONMENT ===
        # If explicit environment provided (per-env batch creation), use it
        # Otherwise, detect from logs (legacy fallback)
        if environment:
            # Explicit environment from ProjectEnvironment config
            batch_environment = environment.name
            logger.info(f"✅ Using explicit environment: {batch_environment}")
        else:
            # Legacy: detect from log labels
            batch_environment = 'production'  # Default
            
            # Build list of known environments from project config + defaults
            known_envs = {
                # Default mappings (case-insensitive)
                'development': 'development', 'dev': 'development',
                'staging': 'staging', 'stage': 'staging', 'preprod': 'staging',
                'production': 'production', 'prod': 'production',
            }
            
            # Add project's custom environments (qa, uat, demo, etc.)
            if project:
                try:
                    from Projects.models import ProjectEnvironment
                    project_envs = ProjectEnvironment.objects.filter(project=project, is_active=True).values_list('name', flat=True)
                    for env_name in project_envs:
                        known_envs[env_name.lower()] = env_name.lower()
                except Exception as e:
                    logger.debug(f"Could not fetch project environments: {e}")
            
            try:
                for hit in filtered_hits[:10]:
                    source = hit.get('_source', {})
                    env_label = source.get('environment') or source.get('env') or source.get('kubernetes', {}).get('labels', {}).get('environment')
                    if env_label:
                        # Case-insensitive match against known environments
                        env_lower = env_label.lower()
                        if env_lower in known_envs:
                            batch_environment = known_envs[env_lower]
                            logger.info(f"Detected environment from logs: {batch_environment} (from '{env_label}')")
                            break
            except Exception as e:
                logger.warning(f"Failed to detect environment from logs: {e}")
            
        
        # === ENVIRONMENT ISOLATION (STRICT MODE) ===
        # Filter logs to ensure they match the determined batch_environment
        if batch_environment:
            logger.info(f"Applying strict environment isolation for '{batch_environment}'")
            pre_env_filter_count = len(filtered_hits)
            
            filtered_hits = [
                log for log in filtered_hits 
                if is_log_matching_environment(log, batch_environment)
            ]
            
            dropped_count = pre_env_filter_count - len(filtered_hits)
            
            if dropped_count > 0:
                logger.warning(
                    f"⚠️ Dropped {dropped_count} logs that did NOT match environment '{batch_environment}' "
                    f"(Isolation protection active)"
                )
            else:
                logger.info(f"Environment filter: All {len(filtered_hits)} logs matched '{batch_environment}'")
        
        # Fetch metrics for the exact batch window
        if not METRICS_ENABLED:
            # `metrics` must be bound on BOTH branches. It is read
            # unconditionally further down (`preprocess_metrics_for_ai(metrics)
            # if metrics else {}`), so leaving it unassigned here raised
            # UnboundLocalError and took the whole batch down — Celery then
            # retried it to exhaustion. METRICS_ENABLED defaults to FALSE
            # (see the getattr/getenv above), so this was the default path:
            # a Helm-deployed SerOps could not create a single batch, while
            # docker-compose installs were fine only because .env sets it true.
            metrics = {}
            serialized_metrics = {}
            logger.info(f"Metrics collection disabled (METRICS_ENABLED=False). Skipping metrics fetch for project {project_name}.")
        else:
            try:
                metrics = {}

                # Metrics must cover the BATCH's window, not "the last N
                # minutes of right now".
                #
                # These were computed independently of batch_start_time /
                # batch_end_time, so a batch with an explicit window — which is
                # the whole point of the Q5-1 alert-triggered path, and what
                # the chaos harness pins per scenario — carried logs from the
                # requested window and metrics from a completely different one.
                # The AI then correlated the two as if they were simultaneous.
                #
                # Measured on the chaos suite: an exception scenario with a
                # 2-minute window was told about an OOMKill from 14 minutes
                # earlier, because the container-lifecycle query inherited this
                # wider range. It reported a confident MEMORY_HIGH issue
                # against a service that was healthy throughout the window it
                # was asked about.
                if override_active:
                    # An explicitly requested window is honoured exactly.
                    metrics_start_time = batch_start_time
                    metrics_end_time = batch_end_time
                else:
                    # Normal scheduled path: the window since the last batch,
                    # but never reaching back further than one interval — a
                    # stalled scheduler must not trigger an hours-long query.
                    metrics_end_time = batch_end_time
                    metrics_start_time = max(
                        batch_start_time,
                        batch_end_time - timezone.timedelta(minutes=effective_interval),
                    )

                logger.info(f"Fetching metrics with timestamp between {metrics_start_time} and {metrics_end_time}")

                # Use helper to fetch metrics via provider with proper context
                metrics = _fetch_metrics_with_provider(
                    metrics_start_time,
                    metrics_end_time,
                    project_obj=project,
                    project_name_str=project_name,
                    environment_str=batch_environment
                )

                # Log the number of metrics found in each category
                logger.info(f"Found metrics: total={len(metrics['memory_total'])}, free={len(metrics['memory_free'])}, "
                           f"available={len(metrics['memory_available'])}, cpu={len(metrics['cpu'])}")

                # Calculate memory usage percentage
                memory_usage = calculate_memory_usage(metrics)
                metrics['memory_usage_percent'] = memory_usage

                # Calculate CPU usage percentage (skip if pre-computed by provider)
                if 'cpu_usage_percent' not in metrics:
                    cpu_metrics = metrics.get('cpu', [])
                    cpu_usage = calculate_cpu_usage(cpu_metrics)
                    metrics['cpu_usage_percent'] = cpu_usage

                # Serialize for storage, OUTSIDE the fetch error handler.
                #
                # These used to share one try/except whose message read "Error
                # fetching metrics", so when serialization raised — which it did
                # on every Kubernetes batch, because container_lifecycle is a
                # dict and the serializer assumed every value was a point list
                # — the log blamed a fetch that had worked perfectly and the
                # metrics were discarded without a trace. Separate handlers, and
                # a loud warning when points go in but nothing comes out.
                fetched_points = sum(
                    len(v) for v in metrics.values() if isinstance(v, list)
                )
                try:
                    serialized_metrics = serialize_metrics(metrics)
                    if not isinstance(serialized_metrics, dict):
                        raise TypeError(
                            f'serialize_metrics returned {type(serialized_metrics)}'
                        )
                except Exception as ser_exc:                    # noqa: BLE001
                    logger.error(
                        "Metrics SERIALIZATION failed for project %s (the fetch "
                        "succeeded — %s points were collected and are being "
                        "discarded): %s",
                        project_name, fetched_points, ser_exc, exc_info=True,
                    )
                    serialized_metrics = {}

                stored_points = sum(
                    len(m) for m in serialized_metrics.values() if isinstance(m, list)
                )
                if fetched_points and not stored_points:
                    logger.error(
                        "Metrics vanished between fetch and storage for project "
                        "%s: %s points collected, 0 stored. The batch chart will "
                        "be empty and metrics will not count toward batch "
                        "creation.", project_name, fetched_points,
                    )
                logger.info(f"Metrics count: {stored_points}")

            except Exception as e:
                logger.error(f"Error fetching metrics for project {project_name}: {e}")
                serialized_metrics = {}

        # Check whether there is anything at all to analyse.
        #
        # Traces are a third signal and count as evidence. Without them here,
        # a latency-only incident — slow spans, HTTP 200 everywhere, no error
        # logs, memory and CPU flat — produced no batch at all, so it never
        # reached the AI. The same omission was already fixed downstream in
        # ``analyze_batch``'s data-presence check; this is the same bug one
        # stage earlier, where it is more damaging because there is no batch
        # left to reanalyse.
        metrics_count = sum(len(m) for m in serialized_metrics.values() if isinstance(m, list)) if serialized_metrics else 0
        trace_span_count = 0
        if not filtered_hits and metrics_count == 0:
            from ai_model.trace_context import count_spans_in_window
            trace_span_count = count_spans_in_window(project, batch_start_time, batch_end_time)

        # An investigation goes on to count code changes and CI/CD runs too:
        # "analyze this deploy" may have nothing else to show.
        if not filtered_hits and metrics_count == 0 and trace_span_count == 0 and not manual:
            logger.info(f"No new unique logs, metrics or traces found for project {project_name}. Batch will not be created.")
            return f"No new logs or metrics found to create batch for project {project_name}"
        if trace_span_count:
            logger.info(
                f"No logs or metrics for project {project_name}, but {trace_span_count} "
                f"trace spans in window — creating batch on trace evidence alone."
            )

        # Prepare data and clean it before saving
        # Create AI-friendly metrics summary (compact version for analysis)
        metrics_summary = preprocess_metrics_for_ai(metrics) if metrics else {}
        
        
        
        # === FETCH CODE CHANGES VIA DEPLOYMENTS ===
        # Query code changes that were DEPLOYED to this environment (not just committed)
        code_changes_data = []
        try:
            from providers.deployment_service import DeploymentService
            
            # Get organisation_id for multi-tenancy isolation (P1 FIX)
            org_id = project.organisation_id if project and project.organisation_id else None
            
            # Get code changes deployed to this environment during batch window
            # Include ALL statuses (success, failed, canceled) for root cause analysis
            code_changes = DeploymentService.get_deployments_for_batch(
                environment=batch_environment,
                start_time=batch_start_time,
                end_time=batch_end_time,
                organisation_id=org_id,  # P1 FIX: Org-level filtering at query time
                only_successful=False  # Include failed for root cause analysis
            )
            
            # Filter by project's registered SCM bindings (provider-agnostic)
            if project and code_changes:
                try:
                    from Projects.models import ProjectService
                    scm_project_ids = set()
                    for svc in ProjectService.objects.filter(project=project):
                        if svc.scm_binding:
                            scm_project_ids.add(str(svc.scm_binding.repository_id))
                    if scm_project_ids:
                        code_changes = [
                            cc for cc in code_changes
                            if str(cc.project_id) in scm_project_ids
                        ]
                except Exception as e:
                    logger.debug(f"Could not filter by project services: {e}")
            
            # Prepare for AI (use existing format)
            from providers.code_change_service import CodeChangeService
            code_changes_data = CodeChangeService.prepare_changes_for_ai(code_changes)
            
            logger.info(
                f"✅ Found {len(code_changes_data)} code changes deployed to "
                f"{batch_environment} for project {project_name}"
            )
        except Exception as e:
            logger.warning(f"Failed to fetch code changes via deployments for project {project_name}: {e}")
        
        # === FETCH CI/CD LOGS VIA PROVIDER ABSTRACTION ===
        cicd_logs_data = []
        try:
            if project_name:
                from integrations.schemas import LogStream
                from providers.tasks import filter_error_warning_lines

                # Org-scoped CI/CD log stream (used for index/stream routing)
                org_slug = getattr(
                    getattr(project, 'organisation', None), 'slug', 'default'
                )
                cicd_stream = LogStream(
                    category='cicd', org_slug=org_slug,
                    project=project_name, environment=batch_environment,
                )

                # Build provider-agnostic query for CI/CD events
                cicd_query = LogQuery(
                    time_range=(batch_start_time, batch_end_time),
                    environment=batch_environment,
                    category='cicd',
                    project=project_name,
                    max_results=100,
                )

                # Search using the provider abstraction
                cicd_results = []
                try:
                    cicd_results = provider.search(
                        index=cicd_stream.to_index_name(),
                        query=cicd_query,
                        size=100,
                    )
                except Exception as e:
                    logger.debug(f"CI/CD search on {cicd_stream.to_index_name()} failed: {e}")

                # Deduplicate by pipeline_id + job_name (prefer records with trace)
                seen_jobs = {}
                for entry in cicd_results:
                    source = entry.labels
                    pipeline_info = source.get('pipeline', {})
                    job_info = source.get('job', {})
                    p_id = pipeline_info.get('id')
                    j_name = job_info.get('name')
                    raw_trace = source.get('trace', '')

                    key = (p_id, j_name)
                    if key in seen_jobs and seen_jobs[key].get('trace'):
                        continue
                    if key not in seen_jobs or raw_trace:
                        filtered_trace_lines = filter_error_warning_lines(raw_trace) if raw_trace else []
                        trace_for_ai = '\n'.join(filtered_trace_lines[:20]) if filtered_trace_lines else None
                        trace_for_ui = raw_trace[-2000:] if raw_trace else None

                        meta = source.get('serops_meta', {})

                        seen_jobs[key] = {
                            'pipeline_id': p_id,
                            'job_name': j_name,
                            'status': job_info.get('status'),
                            'environment': source.get('environment') or meta.get('environment', batch_environment),
                            'branch': pipeline_info.get('ref', ''),
                            'timestamp': entry.timestamp.isoformat() if hasattr(entry.timestamp, 'isoformat') else str(entry.timestamp),
                            'duration': job_info.get('duration_seconds'),
                            'message': entry.message or '',
                            'service_name': source.get('service_name') or meta.get('service_name'),
                            'trace': trace_for_ui,
                            'trace_errors': trace_for_ai,
                        }

                cicd_logs_data = list(seen_jobs.values())
                logger.info(
                    f"Found {len(cicd_logs_data)} CI/CD logs for "
                    f"{batch_environment} environment (project: {project_name})"
                )
            else:
                logger.warning("No project_name provided, skipping CI/CD logs fetch to prevent data leakage")
        except Exception as e:
            logger.warning(f"Failed to fetch CI/CD logs: {e}")
        
        # === SKIP EMPTY BATCHES ===
        # Don't create batches for environments with no data.
        #
        # This is the second emptiness gate in this function and it counts
        # traces for the same reason the first one does: a latency regression
        # produces slow spans and nothing else, and dropping the window here
        # means the incident never becomes a batch at all. ``trace_span_count``
        # was computed by the earlier gate, which runs only on the same
        # logs-and-metrics-empty path that reaches this branch.
        total_data_points = (len(filtered_hits) + metrics_count + len(code_changes_data)
                             + len(cicd_logs_data) + trace_span_count)
        if investigation is not None:
            investigation.counts = {
                'logs': len(filtered_hits), 'metrics': metrics_count, 'traces': trace_span_count,
                'code_changes': len(code_changes_data), 'cicd': len(cicd_logs_data),
            }
            investigation.save(update_fields=['counts'])
        if total_data_points == 0:
            logger.info(f"⏭️ Skipping batch for {batch_environment}: no data (0 logs, 0 metrics, 0 traces, 0 code changes, 0 CI/CD logs)")
            if investigation is not None:
                investigation.finish(investigation.STATUS_NO_DATA)
            try:
                from Data.self_metrics import BATCH_CREATED
                BATCH_CREATED.labels(outcome='skipped').inc()
            except Exception:
                pass
            return {
                'status': 'skipped',
                'reason': 'no_data',
                'environment': batch_environment,
                'project': project_name
            }
        
        # FINAL STEP: Convert LogEntry objects to dicts for JSON storage
        filtered_hits = [
            log.to_legacy_dict() if hasattr(log, 'to_legacy_dict') else log 
            for log in filtered_hits
        ]

        batch_data = {
            'logs': filtered_hits,
            'metrics': serialized_metrics,  # Raw metrics for visualization
            'metrics_summary': metrics_summary,  # Compact summary for AI analysis
            'code_changes': code_changes_data,  # Code changes DEPLOYED to this environment
            'cicd_logs': cicd_logs_data,  # CI/CD logs for this environment
            'statistics': {
                'total_logs': len(filtered_hits),
                'total_metrics': metrics_count,
                'total_code_changes': len(code_changes_data),
                'total_cicd_logs': len(cicd_logs_data),
                'time_range': {
                    'start': batch_start_time.isoformat(),
                    'end': batch_end_time.isoformat()
                },
                'project_name': project_name,  # Add project name to statistics
                'environment': batch_environment  # Add environment to statistics
            },
            # No 'ai_analysis' seed: nothing ever wrote to that key, and the
            # readers that looked there returned empty for every batch. The
            # analysis lands on data['analysis_result'] via save_analysis.
        }
        if investigation is not None and investigation.hint:
            # What the engineer saw; the prompt quotes it as a report.
            batch_data['operator_context'] = investigation.hint
        cleaned_data = clean_json(batch_data)

        project_instance = project

        # === PRE-CREATION SENTINEL GATE (Batch 50) ===
        # Drop noise batches BEFORE the DB row is written. Prevents
        # multi-region × multi-env × N projects from writing hundreds
        # of quiet batch rows/hour. Only fires when active_mode=True
        # AND pre_creation_gate_enabled=True on the org's SentinelConfig.
        # Shadow-mode orgs + orgs that opted out always fall through
        # to persist + evaluate at analysis time (legacy path).
        #
        # This call MUTATES ProjectEnvironmentState (rolling averages,
        # batches_since_last_ai counter). We record that we ran Sentinel
        # here so the post-persist call below skips its own evaluate,
        # preventing double-counting.
        sentinel_result = None  # (decision, triggers) if pre-eval ran
        try:
            # Never for an investigation: a user asked for it, and its window
            # must not feed Sentinel's rolling baseline either.
            if project_instance and environment and not manual:
                from Data.sentinel import should_skip_batch_pre_creation

                should_skip, decision, triggers = should_skip_batch_pre_creation(
                    project=project_instance,
                    environment=environment,
                    batch_data=cleaned_data,
                    organisation=project_instance.organisation,
                )
                sentinel_result = (decision, triggers)
                if should_skip:
                    # Metric — visibility into how many quiet windows
                    # we dropped. Bounded cardinality (org label only).
                    try:
                        from Data.self_metrics import BATCH_CREATED
                        BATCH_CREATED.labels(outcome='skipped_precreation').inc()
                    except Exception:
                        pass
                    logger.info(
                        f"Sentinel pre-creation gate: SKIPPING batch for "
                        f"{project_name}/{batch_environment} — decision={decision} "
                        f"(no persist, no AI, ProjectEnvironmentState still updated)"
                    )
                    return f"Skipped: quiet window ({project_name}/{batch_environment})"
        except Exception as _gate_exc:
            # Fail-open: gate check must NEVER block batch creation.
            # Skipping on gate error would silently lose data.
            logger.warning(
                f"Pre-creation Sentinel gate raised (persisting batch anyway): {_gate_exc}"
            )
            sentinel_result = None

        # Batch 49 — bypass model-level ``editable=False`` on environment
        # by writing via ``_meta.get_field`` at the create call. Django
        # ORM honours editable=False for FORMS/serializers, not for
        # direct .objects.create(), which is exactly the boundary we
        # want: the pipeline sets it here (authoritative source), UI
        # writes are blocked (drift prevention).
        batch = AIAnalyzedBatch.objects.create(
            batch_id=batch_id,
            timestamp=current_time,
            logs_analyzed=len(filtered_hits),
            indices_covered=[index_pattern or index_name or ''],
            data=cleaned_data,
            project=project_instance,  # Link to project if found
            organisation=project_instance.organisation if project_instance else None,
            environment=batch_environment,
            deployment=deployment,  # Batch 49 — deployment-aware routing
            trigger=trigger,
            investigation=investigation,
        )

        # Calculate and update token count
        batch.calculate_tokens_from_logs()

        # Snapshot distributed traces onto batch.data['traces'] so the
        # AI prompt (and any reanalysis or UI view) reasons over exactly
        # what existed in the window, not whatever the DB looks like
        # weeks later after retention. Wrapped internally — never fails
        # the batch.
        try:
            from ai_model.trace_context import snapshot_trace_context
            snapshot_trace_context(batch)
        except Exception as _trace_exc:
            logger.warning(f"Trace snapshot failed for batch {batch_id}: {_trace_exc}")

        # Snapshot enabled data-source capabilities onto batch.data so the
        # prompt builder, correlation engine, and frontend all agree on
        # what was visible when this batch ran. If a user connects
        # Prometheus tomorrow, older batches still show as "no metrics
        # available" rather than lying about coverage.
        try:
            from Organisations.capability_registry import enabled_capabilities_for
            if project_instance is not None:
                caps = sorted(enabled_capabilities_for(project_instance))
                batch.data['project_capabilities'] = caps
                batch.save(update_fields=['data'])
        except Exception as _cap_exc:
            logger.warning(f"Capability snapshot failed for batch {batch_id}: {_cap_exc}")

        # Self-metrics: successful batch creation (Item #24).
        try:
            from Data.self_metrics import BATCH_CREATED
            BATCH_CREATED.labels(outcome='created').inc()
        except Exception:
            pass

        # === SENTINEL EVALUATION ===
        # Batch 50 — reuse the pre-creation gate's result if it ran.
        # Prevents double-mutation of ProjectEnvironmentState and
        # double-log of the decision. When ``sentinel_result`` is set,
        # the pre-gate already called ``evaluate_batch`` upstream +
        # decided NOT to skip; we just copy the decision onto the
        # persisted batch here.
        skip_ai = False
        try:
            if manual:
                batch.sentinel_decision = 'manual'
                batch.save(update_fields=['sentinel_decision'])
            elif project_instance and environment:
                from Data.sentinel import evaluate_batch as sentinel_evaluate, _get_sentinel_config

                if sentinel_result is not None:
                    decision, triggers = sentinel_result
                    active_mode, _ = _get_sentinel_config(project_instance.organisation)
                else:
                    active_mode, thresholds = _get_sentinel_config(project_instance.organisation)
                    decision, triggers = sentinel_evaluate(
                        project=project_instance,
                        environment=environment,
                        batch_data=cleaned_data,
                        organisation=project_instance.organisation,
                        thresholds=thresholds,
                    )
                batch.sentinel_decision = decision
                batch.sentinel_triggers = triggers
                batch.save(update_fields=['sentinel_decision', 'sentinel_triggers'])
                logger.info(
                    f"Sentinel: {decision} for {project_name}/{batch_environment} "
                    f"triggers={triggers} active={active_mode}"
                )

                if active_mode and decision == 'quiet':
                    batch.ai_skipped = True
                    batch.save(update_fields=['ai_skipped'])
                    logger.info(f"Sentinel: SKIPPING AI for batch {batch.batch_id} (quiet, active mode)")
                    skip_ai = True
            else:
                logger.debug(
                    f"Sentinel skipped for batch {batch.batch_id}: "
                    f"no project_instance or environment"
                )
        except Exception as e:
            logger.warning(f"Sentinel evaluation failed for batch {batch.batch_id}: {e}")
        # === END SENTINEL ===

        # Trigger AI analysis (unless sentinel skipped it)
        if not skip_ai:
            try:
                analyze_batch.delay(batch.batch_id)
                logger.info(f"Directly queued analysis for batch {batch.batch_id}")
            except Exception as e:
                logger.error(f"Failed to queue analysis: {str(e)}")

        logger.info(f"Successfully created batch {batch.batch_id} for project {project_name} with {len(filtered_hits)} new logs and {batch.token_count} tokens")
        if investigation is not None:
            investigation.status = investigation.STATUS_ANALYZING
            investigation.save(update_fields=['status'])
            return {'status': 'created', 'batch_id': batch.batch_id}
        return f"Successfully created batch {batch.batch_id} for project {project_name}"

    except Exception as e:
        if investigation is not None:
            # No retry: the user is watching the run, and a retry minutes
            # later would answer a question about a window that has moved on.
            logger.error(f"Investigation {investigation.pk} failed collecting data: {e}", exc_info=True)
            investigation.finish(investigation.STATUS_FAILED, 'collection_failed',
                                 'Collecting data failed. Check the integration settings, then try again.')
            return {'status': 'error', 'reason': 'collection_failed'}
        logger.error(f"Error creating log batch with project name {project_name} (attempt {self.request.retries + 1}/3): {str(e)}", exc_info=True)
        # Retry with exponential backoff (10s, 20s, 40s)
        raise self.retry(exc=e, countdown=10 * (2 ** self.request.retries))
    finally:
        _release_task_lock(lock_key)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    priority=7,  # Phase 2: High but not highest (scale 0-10)
    queue='normal'
)
def create_batches_for_all_projects(self):
    """
    Create separate batches for each project, where each batch includes:
    1. The project's CI/CD logs
    2. The project's application logs
    3. All system logs

    Called every BASE_TICK_RATE minutes (default 1).  Per-org batch intervals
    are respected by checking a Redis timestamp of the last batch run for each
    organisation and skipping orgs whose interval has not elapsed.
    """
    from django.core.cache import cache
    from Data.batch_config import get_batch_interval_for_org

    # === SYNC RECENT DEPLOYMENTS FROM GITLAB ===
    # Queries GitLab API directly to ensure CodeChange + Deployment records exist
    # This handles cases where webhooks were missed (service restart, network issues)
    try:
        from providers.tasks import sync_recent_deployments
        sync_result = sync_recent_deployments(hours=2)  # Sync last 2 hours
        logger.info(f"Deployment sync before batch: {sync_result}")
    except Exception as e:
        logger.warning(f"Pipeline sync failed (continuing with batch creation): {e}")

    # Get all projects from the database that have an Elasticsearch index defined
    # Legacy: used es_index_name. Now we use LogProvider.get_indices() for discovery.
    projects = Project.objects.filter(
        es_index_name__isnull=False
    ).exclude(es_index_name='').select_related('organisation')
    logger.info(f"Found {len(projects)} projects in database with defined Elasticsearch indices")

    # ── Group projects by organisation ──
    from collections import defaultdict as _defaultdict
    org_projects = _defaultdict(list)
    for project in projects:
        org = getattr(project, 'organisation', None)
        org_id = getattr(org, 'id', None)
        org_projects[org_id].append(project)

    # ── Per-org interval gating ──
    now_ts = timezone.now().timestamp()
    eligible_orgs = {}  # org_id -> interval_minutes
    skipped_orgs = []

    for org_id, org_projs in org_projects.items():
        org = org_projs[0].organisation if org_projs else None
        interval = get_batch_interval_for_org(org)
        last_run_key = f'batch_last_run:org:{org_id}'
        last_run_ts = cache.get(last_run_key)

        if last_run_ts is not None and (now_ts - last_run_ts) < interval * 60:
            elapsed = int(now_ts - last_run_ts)
            logger.info(
                f"Skipping org {org_id}: interval={interval}m, "
                f"elapsed={elapsed}s (< {interval * 60}s)"
            )
            skipped_orgs.append(org_id)
            continue

        # Mark this org as running now (TTL = interval + 2 min buffer)
        cache.set(last_run_key, now_ts, timeout=interval * 60 + 120)
        eligible_orgs[org_id] = interval

    logger.info(
        f"Org interval check: {len(eligible_orgs)} eligible, "
        f"{len(skipped_orgs)} skipped (interval not elapsed)"
    )

    # Cache providers per-org to avoid repeated lookups within the same loop
    _provider_cache = {}

    def _get_provider_for_project(proj):
        """Resolve log provider scoped to the project's organisation."""
        org = getattr(proj, 'organisation', None)
        org_id = getattr(org, 'id', None)
        if org_id not in _provider_cache:
            try:
                _provider_cache[org_id] = IntegrationRegistry.get_log_provider_for_org(org)
            except Exception as exc:
                logger.error("Failed to get log provider for org %s: %s", org_id, exc)
                _provider_cache[org_id] = None
        return _provider_cache[org_id]

    # Get system indices via the first eligible project's provider (system indices are shared)
    eligible_projects = [p for oid in eligible_orgs for p in org_projects[oid]]
    first_provider = _get_provider_for_project(eligible_projects[0]) if eligible_projects else None
    system_indices = []
    try:
        if first_provider and hasattr(first_provider, 'client'):
            indices_response = first_provider.client.cat.indices(index="system-*", h="index", format="json")
            system_indices = [index['index'] for index in indices_response]
            logger.info(f"Found {len(system_indices)} system indices: {system_indices}")
    except Exception as e:
        logger.error(f"Error getting system indices: {str(e)}")

    # === PARALLEL BATCH PROCESSING ===
    # Instead of sequential processing, collect all batch tasks and execute in parallel
    # This reduces total processing time from 25+ minutes to 3-5 minutes
    from celery import group
    from Projects.models import ProjectService, ProjectEnvironment

    batch_tasks = []
    skipped_projects = []

    # Collect all batch tasks to execute in parallel (only for eligible orgs)
    for org_id, interval in eligible_orgs.items():
        for project in org_projects[org_id]:
            try:
                # Skip projects with no registered services
                service_count = ProjectService.objects.filter(project=project).count()
                if service_count == 0:
                    logger.info(f"Skipping project '{project.name}': no services registered")
                    skipped_projects.append({project.name: "skipped_no_services"})
                    continue

                # Collect all indices for this project via LogProvider
                project_indices = []
                log_provider = _get_provider_for_project(project)
                if log_provider is None:
                    logger.error(f"No log provider available for project '{project.name}' (org: {getattr(project, 'organisation', None)})")
                    skipped_projects.append({project.name: "no_log_provider"})
                    continue

                # Use LogProvider.get_indices() for application logs discovery
                try:
                    discovered_indices = log_provider.get_indices(project)
                    if discovered_indices:
                        project_indices.extend(discovered_indices)
                        logger.info(f"Discovered {len(discovered_indices)} indices for project '{project.name}': {discovered_indices}")
                except Exception as e:
                    logger.warning(f"Failed to discover indices via provider for project '{project.name}': {e}")

                # Fallback: check legacy es_index_name if provider didn't find anything
                if not project_indices and project.es_index_name:
                    try:
                        if hasattr(log_provider, 'client') and log_provider.client.indices.exists(index=project.es_index_name):
                            project_indices.append(project.es_index_name)
                            logger.info(f"Fallback: Found CI/CD index: {project.es_index_name}")
                        else:
                            logger.warning(f"CI/CD index {project.es_index_name} doesn't exist")
                    except Exception as e:
                        logger.warning(f"Error checking legacy index: {e}")

                # Check app_logs_index_name fallback
                if hasattr(project, 'app_logs_index_name') and project.app_logs_index_name:
                    try:
                        if hasattr(log_provider, 'client') and log_provider.client.indices.exists(index=project.app_logs_index_name):
                            project_indices.append(project.app_logs_index_name)
                            logger.info(f"Found application logs index: {project.app_logs_index_name}")
                    except Exception as e:
                        logger.warning(f"Error checking app logs index: {e}")

                # If no project indices exist, skip this project
                if not project_indices:
                    logger.warning(f"No valid indices found for project '{project.name}'")
                    skipped_projects.append({project.name: "No valid indices found"})
                    continue

                # Combine project's indices with all system indices
                indices_for_project = project_indices + system_indices
                combined_indices = ",".join(indices_for_project)

                # Extract project name — prefer project.name over index parsing
                project_name = project.name

                # === PER-DEPLOYMENT BATCH CREATION (Batch 49) ===
                # Iterate ProjectDeployment (env × cluster × region ×
                # namespace) instead of the old (project × env) tuple.
                # This is what unlocks multi-region, per-env cluster,
                # and namespace-scoped analysis without duplicating
                # Project rows.
                #
                # Deployments are auto-created by post_save signals on
                # ProjectEnvironment + Project (Batch 48 signals) so
                # existing projects post-migration + new projects both
                # have the right rows. Falls back to the env-based path
                # only in the extreme case where a project somehow has
                # ZERO deployments (should be impossible post-migration).
                from Projects.models import ProjectDeployment
                active_deployments = list(
                    ProjectDeployment.objects.filter(
                        project=project, is_active=True,
                    ).select_related('environment', 'cluster')
                )

                if not active_deployments:
                    # Extreme fallback — projects with 0 deployments are
                    # a bug (signals should have auto-created them). Do
                    # ONE legacy env-less batch to avoid data loss + log
                    # loudly so ops notice.
                    logger.warning(
                        f"Project '{project.name}' has no active deployments — "
                        f"falling back to legacy batch creation. "
                        f"Check Batch 48 migration ran + signals wired."
                    )
                    task = create_log_batch_with_project_name.si(
                        index_name=combined_indices,
                        project_name=project_name,
                        project=project.id,
                        interval_minutes=interval,
                    )
                    batch_tasks.append(task)
                    continue

                logger.info(
                    f"Project '{project.name}' has {len(active_deployments)} "
                    f"active deployment(s)"
                )
                for dep in active_deployments:
                    env_id = dep.environment_id  # nullable — env=None deployments are OK
                    env_label = dep.environment.name if dep.environment_id else 'default'
                    logger.info(
                        f"Queuing batch task for project '{project.name}' / "
                        f"deployment '{dep.name}' (env={env_label})"
                    )
                    task = create_log_batch_with_project_name.si(
                        index_name=combined_indices,
                        project_name=project_name,
                        project=project.id,
                        environment=env_id,           # legacy compat — still passed
                        deployment=dep.id,             # Batch 49 — new deployment FK
                        interval_minutes=interval,
                    )
                    batch_tasks.append(task)

            except Exception as e:
                logger.error(f"Error preparing tasks for project {project.name}: {str(e)}")
                skipped_projects.append({project.name: f"Error: {str(e)}"})

    # Execute all batch tasks in parallel using Celery group
    if batch_tasks:
        logger.info(f"Starting {len(batch_tasks)} batch creation tasks in parallel (was sequential)")
        job = group(batch_tasks)
        result_group = job.apply_async()

        logger.info(f"Launched {len(batch_tasks)} parallel batch tasks. Group ID: {result_group.id}")
        return {
            'status': 'parallel_execution_started',
            'total_tasks': len(batch_tasks),
            'skipped_projects': len(skipped_projects),
            'skipped_orgs': len(skipped_orgs),
            'group_id': str(result_group.id),
            'skipped_details': skipped_projects
        }
    else:
        logger.warning("No batch tasks to execute")
        return {
            'status': 'no_tasks',
            'total_tasks': 0,
            'skipped_projects': len(skipped_projects),
            'skipped_orgs': len(skipped_orgs),
            'skipped_details': skipped_projects
        }


@shared_task
def trim_raw_metric_payloads(batch_size=200):
    """Drop raw metric points from old batches, keeping everything else.

    Raw points are 93% of a batch's stored payload (measured: 69 KB of 74 KB)
    and serve one purpose — the batch metrics chart. The analysis, the issues
    and ``metrics_summary`` (per-service statistics and anomalies, which is what
    the AI reasoned over) are the other 7% and are kept.

    This exists because the alternative was nothing. ``run_auto_retention_cleanup``
    deletes whole batches, which is all-or-nothing and takes the analysis with
    it, and it only runs when an organisation has opted into
    ``auto_cleanup_enabled`` — which defaults to False. So on a default install
    the heaviest part of the payload accrued forever: roughly 10 MB per day per
    project at a ten-minute batch interval.

    Unlike whole-batch deletion this runs regardless of ``auto_cleanup_enabled``,
    because unbounded growth is the worse default and what is shed is chart
    detail on a batch old enough that nobody is looking at its chart. Set
    ``raw_metrics_retention_days`` to 0 to keep them for the batch's lifetime.

    Idempotent: a batch whose points are already gone is skipped by the filter,
    not rewritten.
    """
    from Data.models import RetentionPolicy

    trimmed_total = 0
    freed_bytes = 0

    for policy in RetentionPolicy.objects.select_related('organisation'):
        days = policy.raw_metrics_retention_days or 0
        if days <= 0:
            continue

        cutoff = timezone.now() - timezone.timedelta(days=days)
        qs = AIAnalyzedBatch.objects.filter(
            project__organisation=policy.organisation,
            timestamp__lt=cutoff,
        ).exclude(data__metrics=None).only('id', 'data')

        trimmed = 0
        for batch in qs.iterator(chunk_size=batch_size):
            data = batch.data or {}
            raw = data.get('metrics')
            if not raw:
                continue
            try:
                freed_bytes += len(json.dumps(raw))
            except (TypeError, ValueError):
                pass
            # Replaced with an empty dict rather than removed, so readers that
            # assume the key exists keep working.
            data['metrics'] = {}
            data['metrics_trimmed_at'] = timezone.now().isoformat()
            batch.data = data
            batch.save(update_fields=['data'])
            trimmed += 1

        if trimmed:
            logger.info(
                'Trimmed raw metric points from %s batches older than %s days '
                'for org %s', trimmed, days, policy.organisation.name,
            )
        trimmed_total += trimmed

    return {
        'batches_trimmed': trimmed_total,
        'approx_bytes_freed': freed_bytes,
    }


# Below is run_auto_retention_cleanup starting at @shared_task
@shared_task
def run_auto_retention_cleanup():
    """
    Periodic task to clean up old data based on retention policies.
    """
    logger.info("Starting auto-retention cleanup task")
    try:
        policies = RetentionPolicy.objects.filter(auto_cleanup_enabled=True)
        logger.info(f"Found {policies.count()} active retention policies")
        
        for policy in policies:
            # Check if it's time to run based on frequency
            if not policy.should_run_cleanup():
                logger.info(f"Skipping cleanup for {policy.organisation.name} - schedule not met")
                continue
                
            logger.info(f"Running cleanup for {policy.organisation.name}")
            
            # 1. Clean up batches
            cutoff_date = timezone.now() - timezone.timedelta(days=policy.retention_days)
            old_batches = AIAnalyzedBatch.objects.filter(
                project__organisation=policy.organisation,
                timestamp__lt=cutoff_date
            )
            count = old_batches.count()
            
            if count > 0:
                # Log the deletion
                log_batch_delete(
                    request=None,
                    batch_count=count,
                    is_auto=True,
                    retention_days=policy.retention_days,
                    organisation=policy.organisation
                )
                old_batches.delete()
                logger.info(f"Deleted {count} old batches for org {policy.organisation.name}")
            
            # 2. Clean up Audit Logs (if configured)
            if policy.audit_log_retention_days > 0:
                audit_cutoff = timezone.now() - timezone.timedelta(days=policy.audit_log_retention_days)
                old_logs = AuditLog.objects.filter(
                    organisation=policy.organisation,
                    created_at__lt=audit_cutoff
                )
                log_count = old_logs.count()
                if log_count > 0:
                    old_logs.delete()
                    logger.info(f"Deleted {log_count} old audit logs for {policy.organisation.name}")
            
            # Update last cleanup timestamp
            policy.last_cleanup_at = timezone.now()
            policy.last_cleanup_count = count
            policy.save()
            
    except Exception as e:
        logger.error(f"Error in auto-retention cleanup: {str(e)}", exc_info=True)


@shared_task(
    bind=True,
    name='Data.tasks.reset_demo_org',
    queue='background',
    # No automatic retries — if the seed itself fails, the previous
    # day's data is still in place and visitors are unaffected. We
    # prefer a stale demo to a broken one.
    max_retries=0,
)
def reset_demo_org(self):
    """Rebuild the public Acme Cloud demo from scratch.

    Scheduled nightly at 02:00 UTC via Celery Beat (see api/celery.py).
    Delegates to the ``seed_demo_org`` management command so the same
    code path works on the command line for self-hosters and on the
    schedule for the hosted demo.

    A distributed lock prevents two workers from rebuilding in parallel
    if the schedule overlaps with a manual run. Failures degrade open:
    yesterday's data stays in place and the task simply logs the
    error.
    """
    lock_key = 'task_lock:reset_demo_org'
    if not _acquire_task_lock(lock_key, ttl=600):
        logger.info("reset_demo_org already running; skipping")
        return 'Skipped: another instance is running'

    try:
        from django.core.management import call_command
        from Organisations.models import Organisations

        # Skip cleanly when no deployment has a demo configured — keeps
        # this safe to enable on every install without surprises.
        if not Organisations.objects.filter(is_demo=True).exists():
            logger.info("No demo organisation present; skipping reset")
            return 'Skipped: no demo organisation configured'

        call_command('seed_demo_org', verbosity=0)
        logger.info("Demo organisation reset complete")
        return 'Demo organisation reset complete'
    except Exception as e:
        logger.error(f"Error resetting demo organisation: {e}", exc_info=True)
        # Return rather than raise — we never want this background task
        # to retry on its own. The next scheduled run will try again.
        return f'Error: {e}'
    finally:
        _release_task_lock(lock_key)


# ---------------------------------------------------------------------------
# Similar-incidents embedding (Item #27)
# ---------------------------------------------------------------------------


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    priority=3,
    queue='celery',
)
def embed_resolved_issue(self, issue_id):
    """
    Compute + persist an embedding for a resolved issue.

    Called from the ``Issue.save()`` post-save signal when
    ``status`` transitions to ``RESOLVED``. Idempotent — safe to
    re-run; the vector is rewritten.

    Failures retry twice; if OpenAI is down for hours the issue
    just lacks an embedding and future find_similar calls skip it
    (graceful degradation, not a crash).
    """
    from Data.embeddings import embed_text, text_for_issue
    from Data.models import Issue

    issue = Issue.objects.filter(pk=issue_id).only(
        'id', 'root_cause', 'recommendation', 'description',
        'resolution_root_cause', 'resolution_fix',
        'component', 'issue_type',
    ).first()
    if issue is None:
        logger.warning('embed_resolved_issue: Issue %s not found', issue_id)
        return {'status': 'skipped', 'reason': 'not_found'}

    text = text_for_issue(issue)
    if not text.strip():
        return {'status': 'skipped', 'reason': 'no_text'}

    try:
        vector = embed_text(text)
    except Exception as exc:
        logger.warning('embed_resolved_issue: embed_text raised: %s', exc)
        raise self.retry(exc=exc)

    if vector is None:
        return {'status': 'skipped', 'reason': 'embedding_returned_none'}

    Issue.objects.filter(pk=issue_id).update(
        embedding=vector, embedded_at=timezone.now(),
    )
    return {'status': 'embedded', 'issue_id': issue_id, 'dim': len(vector)}


# ---------------------------------------------------------------------------
# On-demand alert analysis (Item #14)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Alert-triggered helpers (Q5-1 + Q5-2)
# ---------------------------------------------------------------------------

# Radius around the alert's ``received_at`` for the on-demand analysis
# window. ±3 min = 6 minutes total, tight enough that a 30-second
# incident isn't diluted by 15 minutes of unrelated logs, wide enough
# to catch a pre-cursor pattern that fired a few minutes before the
# threshold breach.
_ALERT_WINDOW_RADIUS_MINUTES = 3


def _alert_window(event):
    """Return (start_iso, end_iso) for the alert-triggered batch.

    Both are ISO-8601 strings so Celery can serialise them across
    the broker (datetimes lose their tzinfo through some serialisers,
    ISO strings survive intact).
    """
    from datetime import timedelta as _td
    from django.utils import timezone as _tz
    anchor = event.received_at or _tz.now()
    return (
        (anchor - _td(minutes=_ALERT_WINDOW_RADIUS_MINUTES)).isoformat(),
        (anchor + _td(minutes=_ALERT_WINDOW_RADIUS_MINUTES)).isoformat(),
    )


def _project_wiring_score(project) -> int:
    """Score how thoroughly a project is wired up — used to break
    resolver ties (RCA audit finding #5, PR-AUDIT5).

    A project with active integrations (SCM, CI/CD) is a stronger
    match for an incoming alert than an empty shell created for a
    seed / audit / accidental duplicate: real production services
    have their observability + delivery paths connected.

    Score is a plain int so ``max(candidates, key=…)`` picks the
    best-wired candidate and the tiebreak is stable + auditable.
    """
    score = 0
    try:
        from Projects.models import SCMBinding, CICDBinding
        if SCMBinding.objects.filter(project_service__project=project).exists():
            score += 2
        if CICDBinding.objects.filter(project_service__project=project).exists():
            score += 2
    except Exception:
        pass
    try:
        if project.services.filter(status__iexact='Active').exists():
            score += 1
    except Exception:
        pass
    return score


def _resolve_alert_project(event):
    """Pick the project for an incoming alert.

    Precedence:
      1. Match by service name AND environment name — a project with
         both a matching service and the alert's environment is the
         confident answer.
      2. Match by service name alone — when multiple candidates exist,
         prefer the one with the most integration wiring (audit finding
         #5, PR-AUDIT5): SCM binding + CI/CD binding + active services.
         Fall back to lowest id if still tied. Ambiguity is logged.
      3. Fall back to the first project in the org so the analysis
         still runs. Also logged as WARNING because it's the weakest
         match.
    """
    from Projects.models import Project

    org = event.organisation
    svc = event.service or ''
    env = event.environment or ''

    def _pick(candidates, reason):
        """Break a candidate tie by wiring score, then lowest id.

        A project with active SCM + CI/CD bindings outranks an empty
        shell even when both match the alert's service name. Logs the
        tiebreak so an operator can see which project was picked and
        why.
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # Rank by (wiring_score DESC, id ASC).
        ranked = sorted(
            candidates,
            key=lambda p: (-_project_wiring_score(p), p.id),
        )
        best = ranked[0]
        logger.warning(
            'analyze_alert_ondemand: %d projects match %s in org=%s (%s) — '
            'picking id=%d (wiring_score=%d) via wiring-then-id tiebreak. '
            'Add a distinct service name per project or wire more integrations '
            'to remove this ambiguity.',
            len(candidates), reason, org.id, [p.id for p in candidates],
            best.id, _project_wiring_score(best),
        )
        return best

    if svc:
        candidates = list(
            Project.objects.filter(
                organisation=org,
                services__name__iexact=svc,
            ).distinct()
        )
        if env and candidates:
            env_matched = [
                p for p in candidates
                if p.environments.filter(name__iexact=env).exists()
            ]
            picked = _pick(env_matched, f'service={svc} env={env}')
            if picked is not None:
                return picked
        picked = _pick(candidates, f'service={svc}')
        if picked is not None:
            return picked

    # No service on the alert, or no candidate — fall back so the
    # analysis still runs. Weak match: worth an operator's attention.
    fallback = Project.objects.filter(organisation=org).order_by('id').first()
    if fallback is not None:
        logger.warning(
            'analyze_alert_ondemand: no service-name match for alert=%s '
            '(service=%r env=%r) in org=%s — falling back to first project '
            'id=%d. Alert-to-project routing is a best-effort proxy; add a '
            'binding-based mapping if this fires often.',
            event.pk, svc, env, org.id, fallback.id,
        )
    return fallback


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=15,
    priority=10,          # highest — alert-triggered analyses jump the queue
    queue='high_priority',
)
def analyze_alert_ondemand(self, alert_event_id):
    """
    Kick off a batch analysis for one incoming alert (Item #14).

    Target latency: alert → analysis complete in <30s.

    Flow:
    1. Load AlertEvent.
    2. Resolve the project by service label (best-effort match).
    3. Call ``create_log_batch_with_project_name`` for the alert's
       service + environment. This is the same batch pipeline the
       scheduler uses — reusing it keeps the analysis quality
       identical to normal batches.
    4. Link the new batch back to the AlertEvent (triggered_batch).
    5. Mark the alert processed.

    All errors swallowed after logging — alerts continue firing at
    the source; a broken analysis path must not create an infinite
    Celery retry loop.
    """
    from Data.models import AlertEvent
    from Projects.models import Project

    event = AlertEvent.objects.filter(pk=alert_event_id).first()
    if event is None:
        logger.warning('analyze_alert_ondemand: AlertEvent %s not found', alert_event_id)
        return {'status': 'skipped', 'reason': 'event_not_found'}

    # Best-effort project lookup — matches by any project in the org
    # whose services include one named like the alert's service.
    #
    # Q5-2: two projects can legitimately share a service name (a
    # microservice "gateway" running in both ``platform-core`` and
    # ``partner-integrations`` projects, for instance). Before this
    # fix the first-match-wins query silently picked one and the
    # analyst had no visibility into the misroute. Now we surface the
    # ambiguity at WARNING and prefer the project the alert's
    # ``environment`` string matches — if the alert declared an env,
    # a project with a matching ProjectEnvironment is the right home.
    project = _resolve_alert_project(event)

    if project is None:
        logger.info(
            'analyze_alert_ondemand: no project in org %s — nothing to analyse',
            event.organisation_id,
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['processed_at'])
        return {'status': 'skipped', 'reason': 'no_project'}

    # Q5-1: alert-triggered analyses should look at a tight window
    # around the alert's arrival, not the scheduler's 15-min back-look.
    # ±3 min centred on ``received_at`` gives us 6 minutes of context —
    # enough to catch pre-cursor patterns without diluting the signal.
    _win_start, _win_end = _alert_window(event)

    # Invoke the standard batch pipeline synchronously — we want the
    # AlertEvent → batch linkage before the task returns. The batch id is
    # chosen here so the link is exact. The environment must be the
    # project's ProjectEnvironment: passing the alert's label as a string
    # crashed the pipeline on its first use, so alert analyses never ran.
    import uuid
    alert_batch_id = f"{project.name.strip().replace(' ', '-').replace('_', '-').lower()}-alert-" \
                     f"{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4]}"
    try:
        result = create_log_batch_with_project_name(
            index_name=project.es_index_name,
            project_name=project.name,
            project=project,
            environment=project.environments.filter(
                name__iexact=event.environment or 'production').first(),
            window_start_iso=_win_start,
            window_end_iso=_win_end,
            trigger=AIAnalyzedBatch.TRIGGER_ALERT,
            batch_id=alert_batch_id,
        )
    except Exception as exc:
        logger.error(
            'analyze_alert_ondemand: batch creation failed for alert %s: %s',
            event.pk, exc, exc_info=True,
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['processed_at'])
        return {'status': 'error', 'error': str(exc)}

    # Link the alert to the batch this run created, if it created one.
    batch = AIAnalyzedBatch.objects.filter(batch_id=alert_batch_id).first()
    if batch is not None:
        event.triggered_batch = batch
    event.processed_at = timezone.now()
    event.save(update_fields=['triggered_batch', 'processed_at'])

    # Outbound `alert_triggered` fan-out — PagerDuty change events +
    # OpsGenie notes typically listen on this event only (they
    # already know about scheduled batches from other tooling).
    if batch is not None:
        try:
            from notifications.incident_dispatcher import dispatch as _incident_dispatch
            _incident_dispatch(batch, event='alert_triggered', alert_event=event)
        except Exception as _n_exc:
            logger.warning(
                'Alert-triggered incident dispatch failed for alert %s: %s',
                event.pk, _n_exc,
            )

    return {
        'status': 'analysed',
        'alert_event_id': event.pk,
        'batch_id': batch.batch_id if batch else None,
        'result': result if isinstance(result, dict) else str(result),
    }


@shared_task(bind=True, max_retries=0, priority=9, queue='high_priority')
def run_investigation(self, investigation_id):
    """Collect and analyse one Investigation's scope and window.

    A thin wrapper: the batch pipeline does the work and records progress
    and the outcome on the Investigation itself.
    """
    return create_log_batch_with_project_name(investigation_id=investigation_id)
