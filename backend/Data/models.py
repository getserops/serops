from datetime import timedelta

from django.db import models
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class AIAnalyzedBatch(models.Model):
    batch_id = models.CharField(max_length=100, unique=True, db_index=True)
    timestamp = models.DateTimeField(default=timezone.now)
    issue_count = models.IntegerField(default=0)
    data = models.JSONField(default=dict)
    logs_analyzed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    indices_covered = models.JSONField(default=list)
    token_count = models.IntegerField(default=0)
    # Add new fields for analysis
    analysis_text = models.TextField(null=True, blank=True)
    analyzed_at = models.DateTimeField(null=True, blank=True)
    model_name = models.CharField(max_length=100, null=True, blank=True, help_text="Nom du modèle d'analyse utilisé")
    
    # Store multiple analysis results from different models for comparison
    analysis_history = models.JSONField(
        default=list,
        blank=True,
        help_text="History of analyses with different models for comparison"
    )
    
    # Direct link to Project for better querying and isolation
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        null=True,  # Nullable for backwards compatibility
        blank=True,
        related_name='batches'
    )

    # Organisation FK for multi-tenancy data isolation
    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        null=True,  # Nullable for backwards compatibility with existing batches
        blank=True,
        related_name='batches',
        help_text='Organisation scope for multi-tenancy isolation'
    )
    
    # Sentinel fields (Phase 1: shadow mode)
    SENTINEL_CHOICES = [
        ('alert', 'Alert — triggers present'),
        ('quiet', 'Quiet — nothing new'),
        ('first', 'First batch for this project+env'),
        ('shadow', 'Shadow mode (always run AI)'),
        ('manual', 'Manual — a user asked for this analysis'),
    ]
    sentinel_decision = models.CharField(
        max_length=20,
        choices=SENTINEL_CHOICES,
        default='shadow',
        help_text='Sentinel triage decision for this batch'
    )
    sentinel_triggers = models.JSONField(
        default=list,
        blank=True,
        help_text='List of trigger reasons from Sentinel evaluation'
    )
    ai_skipped = models.BooleanField(
        default=False,
        help_text='True if AI analysis was skipped by sentinel active mode'
    )

    # IDs of resolved Issue rows that were injected into the AI prompt
    # as Recent Resolutions Context. Persisted per-batch (not per-issue)
    # because the same memory set informs every issue this batch produces.
    referenced_resolution_ids = models.JSONField(
        default=list,
        blank=True,
        help_text='IDs of resolved issues that fed the AI prompt as context.',
    )

    # Cost-visibility instrumentation (added 2026-08-31 with the
    # non-destructive severity filter + Smart Aggregation persist pass).
    # Populated by analyze_batch at the end of prompt construction so
    # the frontend can render "processed N raw logs → M unique patterns
    # → K sent to AI" without recomputing at read time. All default to
    # 0 for legacy rows; only new batches carry meaningful values.
    logs_raw_count = models.IntegerField(
        default=0,
        help_text='Log-event count in batch.data before any prompt-side filtering.',
    )
    logs_after_severity_filter = models.IntegerField(
        default=0,
        help_text='Log count after dropping INFO/DEBUG for the AI prompt.',
    )
    logs_unique_patterns = models.IntegerField(
        default=0,
        help_text='Unique signature count after Smart Aggregation (grouping identical errors).',
    )
    logs_sent_to_ai = models.IntegerField(
        default=0,
        help_text='Actual log-line count sent to the AI (capped by aggregation slots).',
    )

    # Environment for multi-environment support
    ENVIRONMENT_CHOICES = [
        ('development', 'Development'),
        ('staging', 'Staging'),
        ('production', 'Production'),
    ]
    # Batch 49 — environment becomes a read-only mirror populated
    # from deployment.environment.name at batch creation. Kept as a
    # column (not derived at query time) because 20+ analytics views
    # filter directly on batch.environment and rewriting them all
    # would multiply the surgery cost of this batch.
    # ``editable=False`` blocks admin form + serializer writes; the
    # batch pipeline sets it explicitly at ``.create()`` time.
    environment = models.CharField(
        max_length=50,
        choices=ENVIRONMENT_CHOICES,
        default='production',
        db_index=True,
        editable=False,
    )

    # Batch 49 — pointer to the deployment this batch was created
    # for (env × cluster × region × namespace). ``SET_NULL`` so
    # deleting a deployment doesn't nuke its history, and so batches
    # created BEFORE this batch (via the pre-Batch 49 pipeline) can
    # coexist with a NULL FK. New batches from the deployment-aware
    # pipeline always set it.
    deployment = models.ForeignKey(
        'Projects.ProjectDeployment',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='batches',
        help_text='Deployment (env × cluster × region × namespace) this batch analyses.',
    )

    # What created the batch. Only scheduled batches move the scheduler's
    # window and only manual ones skip log dedup history; see
    # get_scheduled_window_start and filter_unique_logs_for_project.
    TRIGGER_SCHEDULED = 'scheduled'
    TRIGGER_ALERT = 'alert'
    TRIGGER_MANUAL = 'manual'
    TRIGGER_CHOICES = [
        (TRIGGER_SCHEDULED, 'Scheduled'),
        (TRIGGER_ALERT, 'Alert'),
        (TRIGGER_MANUAL, 'Investigation'),
    ]
    trigger = models.CharField(
        max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_SCHEDULED, db_index=True,
    )
    investigation = models.OneToOneField(
        'Data.Investigation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='batch',
    )


    class Meta:
        ordering = ['-timestamp']
        verbose_name = "AI Analyzed Batch"
        verbose_name_plural = "AI Analyzed Batches"
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['batch_id']),
            models.Index(fields=['organisation', '-timestamp']),
            models.Index(fields=['deployment', '-timestamp'],
                        name='batch_deploy_ts_idx'),
        ]

    @classmethod
    def generate_batch_id(cls):
        """Generate a unique batch ID including seconds and random suffix"""
        import uuid
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        unique_suffix = str(uuid.uuid4())[:4]
        return f"batch_{timestamp}_{unique_suffix}"

    def calculate_tokens_from_logs(self):
        """
        Estimation du nombre de tokens à partir des messages de logs.
        Environ 1 token pour 4 caractères.
        """
        try:
            logs = self.data.get('logs', [])
            if not logs:
                self.token_count = 0
            else:
                messages = [log.get('_source', {}).get('message', '') for log in logs]
                combined_text = ' '.join(messages)
                self.token_count = len(combined_text) // 4  # Estimation 
            self.save(update_fields=['token_count'])
        except Exception as e:
            logger.error(f"Error calculating tokens from logs: {e}")

    def get_analysis_results(self):
        """Get the AI analysis results for this batch.

        Reads ``data['analysis_result']``, which is where both persistence
        paths write. The previous key, ``data['ai_analysis']``, was seeded as
        an empty dict at batch creation and never filled by anything, so this
        method returned ``{}`` for every batch ever analysed — and the
        serializer field backed by it was always empty.
        """
        return (self.data or {}).get('analysis_result') or {}

    @property
    def has_analysis(self):
        """Check if this batch has been analyzed.

        ``analyzed_at`` is the authoritative marker: it is set by every
        persistence path, including one that stores only a narrative.
        """
        return bool(self.analyzed_at)
    
    def get_analysis_history(self):
        """Get all analysis results for comparison"""
        return self.analysis_history or []
    
    def get_analysis_by_model(self, model_name):
        """Get analysis result for a specific model"""
        for analysis in (self.analysis_history or []):
            if analysis.get('model_name', '').lower() == model_name.lower():
                return analysis
        return None

    @staticmethod
    def extract_narrative(analysis_result):
        """Turn a parsed AI analysis into a short human-readable string.

        RCA audit follow-up (2026-09-20): kept as its own method so
        ``ai_model.tasks._apply_primary_analysis_to_batch`` can set
        ``analysis_text`` directly (during a re-run in ``mode='primary'``)
        without also writing to ``analysis_history`` — the caller
        owns history writes.

        Returns a string capped at 4000 chars, or ``None`` when no
        narrative is recoverable.
        """
        if isinstance(analysis_result, dict):
            correlated = analysis_result.get('correlated_issues') or []
            if correlated and isinstance(correlated[0], dict):
                narrative = correlated[0].get('root_cause') or None
                # Handle the rare "root_cause is itself a nested dict"
                # shape from older prompt outputs.
                if isinstance(narrative, dict):
                    narrative = narrative.get('description') or None
            else:
                narrative = None
            return str(narrative)[:4000] if narrative else None
        if isinstance(analysis_result, str):
            return analysis_result[:4000]
        return None

    def save_analysis(self, analysis_result, model_name=None):
        """Save the analysis result to both data and dedicated fields, and add to history.

        RCA audit follow-up (2026-09-20): ``analysis_text`` is a
        ``TextField`` meant to hold the human-readable RCA hypothesis
        the Batch Detail card renders as prose. Prior code assigned the
        raw ``analysis_result`` dict to it — Django coerced the dict to
        its Python ``repr()`` on save, producing ``{'summary': {...``
        walls of text with single-quoted keys and nested braces that
        rendered as garbage on the frontend. The parsed dict is kept
        under ``batch.data['analysis_result']`` and
        ``batch.analysis_history[-1]['analysis_result']`` for anyone
        who needs the full JSON; ``analysis_text`` now stores only the
        narrative extracted from the first correlated issue via
        ``extract_narrative``.
        """
        if not self.data:
            self.data = {}

        # Persist the parsed dict on ``data`` as well as in history.
        #
        # The docstring below has always promised this and the code never did
        # it: ``data`` was absent from ``update_fields``, so the key never
        # reached the database. ``_persist_primary_analysis`` — the re-analyse
        # and promote path — DOES write it, so the same field existed for a
        # re-analysed batch and not for a normally analysed one. That is the
        # shape of bug that gets reported as "it only works after I click
        # Re-Analyze", and it cost real time here: a harness reading the
        # documented location scored a correct four-issue cascade as zero.
        self.data['analysis_result'] = (
            analysis_result if isinstance(analysis_result, dict) else {}
        )

        current_time = timezone.now()
        self.analysis_text = self.extract_narrative(analysis_result)
        self.analyzed_at = current_time
        if model_name:
            self.model_name = model_name
        
        # Also add to analysis history for comparison
        if self.analysis_history is None:
            self.analysis_history = []
        
        # Create history entry
        history_entry = {
            'model_name': model_name or 'unknown',
            'analyzed_at': current_time.isoformat(),
            'analysis_result': analysis_result if isinstance(analysis_result, dict) else str(analysis_result),
            'is_primary': True  # Mark as primary analysis
        }
        
        # Mark all previous entries as non-primary
        for entry in self.analysis_history:
            entry['is_primary'] = False
        
        # Add new entry
        self.analysis_history.append(history_entry)
        
        # Keep only the last 5 analyses to avoid bloat
        if len(self.analysis_history) > 5:
            self.analysis_history = self.analysis_history[-5:]
        
        self.save(update_fields=['analysis_text', 'analyzed_at', 'model_name',
                                 'analysis_history', 'data'])




class Issue(models.Model):
    SEVERITY_CHOICES = [
        ('CRITICAL', 'Critical'),
        ('WARNING', 'Warning'),
        ('INFO', 'Info'),
        ('UNKNOWN', 'Unknown'),
    ]
    
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('MUTED', 'Muted'),
        ('RESOLVED', 'Resolved'),
    ]
    
    SCOPE_CHOICES = [
        ('SERVICE', 'Service'),
        ('INFRASTRUCTURE', 'Infrastructure'),
        ('PIPELINE', 'Pipeline'),
        ('CODE', 'Code Review'),
    ]
    
    # Fixed issue types for stable fingerprinting
    ISSUE_TYPES = [
        # Application
        ('CONNECTION_TIMEOUT', 'Connection Timeout'),
        ('CONNECTION_REFUSED', 'Connection Refused'),
        ('DATABASE_ERROR', 'Database Error'),
        ('AUTH_FAILURE', 'Authentication Failure'),
        ('PERMISSION_DENIED', 'Permission Denied'),
        ('API_ERROR', 'API Error'),
        ('NULL_POINTER', 'Null Pointer / NPE'),
        ('SERVICE_UNAVAILABLE', 'Service Unavailable'),
        ('RATE_LIMITED', 'Rate Limited'),
        # Infrastructure
        ('MEMORY_HIGH', 'High Memory Usage'),
        ('MEMORY_LEAK', 'Memory Leak'),
        ('CPU_HIGH', 'High CPU Usage'),
        ('DISK_FULL', 'Disk Full'),
        ('NETWORK_ERROR', 'Network Error'),
        ('DNS_FAILURE', 'DNS Failure'),
        # Availability
        ('SERVICE_DOWN', 'Service Down'),
        ('SERVICE_RESTART', 'Service Restart'),
        ('POD_CRASH', 'Pod Crash'),
        ('HEALTH_CHECK_FAILED', 'Health Check Failed'),
        # CI/CD
        ('BUILD_FAILED', 'Build Failed'),
        ('TEST_FAILED', 'Test Failed'),
        ('DEPLOY_FAILED', 'Deploy Failed'),
        ('PIPELINE_TIMEOUT', 'Pipeline Timeout'),
        # Code Review (proactive, from diff analysis)
        ('CODE_QUALITY', 'Code Quality Issue'),
        ('POTENTIAL_BUG', 'Potential Bug'),
        ('SECURITY_RISK', 'Security Risk'),
        ('DEPRECATED_USAGE', 'Deprecated API/Pattern'),
        # Catch-all
        ('OTHER', 'Other'),
    ]

    # The batch in which this issue was MOST RECENTLY seen.
    #
    # Not "the batch that found it": ``move_to_batch`` repoints this on every
    # recurrence. One issue genuinely occurs in many batches, so the batch a
    # given analysis reported is recorded in ``IssueOccurrence`` — see that
    # model for why a single FK cannot answer "what did this batch find?".
    batch = models.ForeignKey(AIAnalyzedBatch, on_delete=models.CASCADE, related_name='issues')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, db_index=True)
    description = models.TextField()
    recommendation = models.TextField(blank=True, null=True)
    root_cause = models.TextField(blank=True, null=True)

    # Step-by-step evidence chain the AI used to reach its conclusion.
    # Populated from the `reasoning` array in the batch-analysis JSON.
    # Stored as plain text with "1. ... 2. ... 3. ..." formatting so the
    # frontend can render it as an ordered list without parsing.
    reasoning = models.TextField(
        blank=True,
        null=True,
        help_text="Step-by-step evidence chain the AI followed (1. observed, 2. checked, 3. concluded).",
    )

    CONFIDENCE_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('UNKNOWN', 'Unknown'),
    ]
    confidence = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        default='UNKNOWN',
        db_index=True,
        help_text="How confident the AI is in this root cause. UNKNOWN when the AI did not report a confidence.",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    # v2 Deduplication fields
    issue_type = models.CharField(max_length=30, choices=ISSUE_TYPES, default='OTHER', db_index=True)
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='SERVICE', db_index=True)
    component = models.CharField(max_length=100, blank=True, default='')
    # Other services showing symptoms of this issue's cause. One shared cause
    # (a cache, DNS, a certificate) is one issue on the component where the
    # cause lives, not one issue per service that noticed it.
    affected_services = models.JSONField(default=list, blank=True)
    environment = models.CharField(max_length=50, blank=True, default='')
    fingerprint = models.CharField(max_length=70, db_index=True, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    muted_until = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    occurrence_count = models.IntegerField(default=1)
    
    # v3 AI Classification fields for smarter deduplication
    ERROR_CLASSES = [
        ('COMMAND_NOT_FOUND', 'Command not found'),
        ('SYNTAX_ERROR', 'Syntax error'),
        ('MODULE_NOT_FOUND', 'Missing module/package'),
        ('DEPENDENCY_CONFLICT', 'Dependency conflict'),
        ('CONNECTION_REFUSED', 'Connection refused'),
        ('CONNECTION_TIMEOUT', 'Connection timeout'),
        ('DNS_FAILURE', 'DNS resolution failed'),
        ('AUTH_FAILED', 'Authentication failed'),
        ('TOKEN_EXPIRED', 'Token/certificate expired'),
        ('PERMISSION_DENIED', 'Permission denied'),
        ('OUT_OF_MEMORY', 'Out of memory'),
        ('DISK_FULL', 'Disk full'),
        ('RESOURCE_LIMIT', 'Resource limit exceeded'),
        ('DB_CONNECTION', 'Database connection error'),
        ('QUERY_ERROR', 'SQL/query error'),
        ('TEST_ASSERTION', 'Test assertion failed'),
        ('BUILD_COMPILE', 'Compilation error'),
        ('DEPLOY_ROLLBACK', 'Deployment rollback'),
        ('CONFIG_ERROR', 'Configuration error'),
        # Code review (proactive detection from diffs)
        ('TYPO', 'Typo / misspelling in code'),
        ('NULL_REFERENCE', 'Potential null/undefined reference'),
        ('RACE_CONDITION', 'Potential race condition'),
        ('UNHANDLED_EXCEPTION', 'Missing error handling'),
        ('OTHER', 'Other/unclassified'),
    ]
    error_class = models.CharField(
        max_length=50, 
        choices=ERROR_CLASSES,
        default='OTHER', 
        db_index=True,
        help_text='AI-classified error category for smart deduplication'
    )
    error_target = models.CharField(
        max_length=200, 
        blank=True, 
        default='',
        help_text='Specific failing item (command, module, host, etc.)'
    )
    
    # Project link for org-level deduplication
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='issues'
    )

    # Organisation FK for null-project isolation (C1 fix)
    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='issues',
    )

    # Resolution tracking for MTTR calculation
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text='When the issue status was changed to RESOLVED'
    )
    resolved_by = models.ForeignKey(
        'Users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resolved_issues', help_text='User who resolved the issue',
    )
    # What the team says actually happened, entered (or confirmed) when
    # resolving. Past-incident memory and similar-incident search prefer
    # these over the AI's own root_cause / recommendation.
    resolution_root_cause = models.TextField(blank=True, null=True)
    resolution_fix = models.TextField(blank=True, null=True)

    # Similar-incidents embedding (Item #27). Populated on resolve by
    # the ``embed_resolved_issue`` Celery task. JSONField list of 1536
    # floats — Python-side cosine similarity for MVP scale. A future
    # migration will move this to a pgvector column when the ops
    # container ships with pgvector (Q3.5 quality-backlog item).
    embedding = models.JSONField(
        null=True,
        blank=True,
        help_text='1536-dim text-embedding-3-small vector of the '
                  'resolved issue. Populated async on resolve.',
    )
    embedded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When embedding was populated. Missing = pending or failed.',
    )

    # Acknowledgment tracking for escalation
    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When the issue was acknowledged'
    )
    acknowledged_by = models.ForeignKey(
        'Users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_issues',
        help_text='User who acknowledged the issue'
    )
    escalation_level = models.IntegerField(
        default=0,
        help_text='Current escalation level (0=none, 1=L1, 2=L2)'
    )
    
    # v4 Pre-computed correlation fields for scalable querying
    has_commit_correlation = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Whether this issue has linked code commits'
    )
    has_metric_correlation = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Whether this issue correlates with metric spikes (memory/CPU)'
    )
    linked_commits = models.JSONField(
        default=list,
        blank=True,
        help_text='List of linked commits: [{sha, provider, project_id, message}]'
    )
    metric_correlation_type = models.CharField(
        max_length=20,
        blank=True,
        default='',
        help_text='Type of metric correlation: memory, cpu, or empty'
    )

    # v5 Engine-driven correlation fields (replacing keyword matching)
    CONFIDENCE_CHOICES = [
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'),
        ('LOW', 'Low'),
        ('', 'None'),
    ]
    correlation_confidence = models.CharField(
        max_length=10,
        choices=CONFIDENCE_CHOICES,
        blank=True,
        default='',
        help_text='Confidence level from correlation engine (HIGH/MEDIUM/LOW)'
    )
    ANOMALY_TYPE_CHOICES = [
        ('spike', 'Spike'),
        ('sustained_high', 'Sustained High'),
        ('', 'None'),
    ]
    metric_anomaly_type = models.CharField(
        max_length=20,
        choices=ANOMALY_TYPE_CHOICES,
        blank=True,
        default='',
        help_text='Type of metric anomaly: spike or sustained_high'
    )
    correlation_details = models.JSONField(
        default=dict,
        blank=True,
        help_text='Full matched correlation data from engine (peak value, duration, commit links, etc.)'
    )
    has_cicd_correlation = models.BooleanField(
        default=False,
        db_index=True,
        help_text='Whether this issue correlates with a CI/CD pipeline failure'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['severity', 'created_at']),
            models.Index(fields=['fingerprint']),
            models.Index(fields=['status']),
            models.Index(fields=['issue_type', 'project', 'component']),
            # v4 Correlation indexes for filtering
            models.Index(fields=['has_commit_correlation']),
            models.Index(fields=['has_metric_correlation']),
            # Past-incident memory lookup (Data/memory.py)
            models.Index(
                fields=['project', 'environment', 'status', '-resolved_at'],
                name='issue_memory_lookup_idx',
            ),
        ]
        constraints = [
            # Primary: fingerprint+project for issues with a project
            models.UniqueConstraint(
                fields=['fingerprint', 'project'],
                condition=models.Q(status__in=['OPEN', 'MUTED'], project__isnull=False),
                name='unique_open_issue_per_fingerprint_project',
            ),
            # Fallback: fingerprint+organisation for null-project issues (C1 fix)
            models.UniqueConstraint(
                fields=['fingerprint', 'organisation'],
                condition=models.Q(status__in=['OPEN', 'MUTED'], project__isnull=True),
                name='unique_open_issue_per_fingerprint_org',
            ),
        ]

    def __str__(self):
        return f"{self.severity} - {self.issue_type} - {self.component or 'N/A'}"

    def find_similar(self, top_k: int = 5, min_similarity: float = 0.75):
        """
        Return the top-K resolved issues most similar to ``self`` by
        embedding cosine similarity (Item #27).

        Filters:

        * Same organisation (never cross-org leakage).
        * Not ``self``.
        * Only resolved issues with a stored embedding.
        * Cosine similarity ≥ ``min_similarity`` (0.75 default —
          empirically strong match for text-embedding-3-small on
          RCA-style text).

        Returns a list of dicts ``{issue, similarity}`` sorted by
        descending similarity. Empty list when no matches or when
        ``self`` has no embedding (embedding is best-effort; queries
        against issues that never got one just return []).

        Cost: O(N) over the org's resolved issues with embeddings.
        Fine at MVP scale; a pgvector migration lands at Q3.5 for
        orgs that push past ~50K resolved issues.
        """
        if not self.embedding:
            return []
        from Data.embeddings import cosine_similarity

        candidates = (
            Issue.objects
            .filter(organisation=self.organisation, status='RESOLVED')
            .exclude(pk=self.pk)
            .exclude(embedding__isnull=True)
            .only('id', 'issue_type', 'component', 'description',
                  'root_cause', 'recommendation', 'resolved_at',
                  'severity', 'embedding')
        )

        scored = []
        for cand in candidates.iterator(chunk_size=500):
            sim = cosine_similarity(self.embedding, cand.embedding or [])
            if sim >= min_similarity:
                scored.append((sim, cand))
        scored.sort(key=lambda t: t[0], reverse=True)

        return [{'issue': c, 'similarity': round(sim, 4)}
                for sim, c in scored[:top_k]]
    
    def save(self, *args, **kwargs):
        """Override save to pre-compute correlation fields, track resolution time, and invalidate caches."""
        # Detect status transition BEFORE we mutate the row — used
        # below to enqueue an embedding on OPEN → RESOLVED.
        _was_resolved = False
        _previous_status = None
        if self.pk:
            try:
                _previous_status = (
                    Issue.objects.only('status').get(pk=self.pk).status
                )
                _was_resolved = _previous_status == 'RESOLVED'
            except Issue.DoesNotExist:
                _was_resolved = False

        # Auto-set resolved_at when status changes to RESOLVED
        if self.status == 'RESOLVED' and not self.resolved_at:
            from django.utils import timezone as tz
            self.resolved_at = tz.now()
        elif self.status != 'RESOLVED':
            self.resolved_at = None

        # Only run keyword-based _compute_correlations as fallback for issues
        # without engine-driven data. Engine data is set by _populate_issue_correlations
        # in ai_model/tasks.py which uses save(update_fields=[...]) to bypass this.
        if not self.pk or kwargs.pop('compute_correlations', False):
            if not self.correlation_details:
                self._compute_correlations()
        super().save(*args, **kwargs)

        # Item #27: embed the resolved form asynchronously so future
        # incidents can find similar past resolutions. Only fires on
        # the OPEN → RESOLVED transition (not repeatedly on re-saves
        # of already-resolved issues) and only when we have text worth
        # embedding.
        if (self.status == 'RESOLVED'
                and not _was_resolved
                and (self.effective_root_cause or self.description)):
            try:
                from Data.tasks import embed_resolved_issue
                embed_resolved_issue.delay(self.pk)
            except Exception as _emb_exc:
                # Task queue outage must not block the resolve action.
                logger.warning(
                    'embed_resolved_issue enqueue failed for issue %s: %s',
                    self.pk, _emb_exc,
                )

        # Phase 2: Invalidate dashboard caches when issues change
        self._invalidate_dashboard_caches()
    
    def _compute_correlations(self):
        """
        Pre-compute correlation fields for scalable querying.
        Called on save() to avoid computing on every API request.
        """
        import re
        
        # Combine text fields for analysis
        text = f"{self.root_cause or ''} {self.recommendation or ''}"
        desc_text = f"{self.description or ''} {self.root_cause or ''}".lower()
        
        # Extract commit SHAs
        pattern = r'commit\s+[`"\']?([a-f0-9]{6,40})[`"\']?'
        commit_matches = re.findall(pattern, text, re.IGNORECASE)
        unique_commits = list(set(commit_matches))
        
        # Build linked_commits with provider context
        self.linked_commits = []
        if unique_commits:
            # Try to get provider info from project
            provider = 'unknown'
            project_id = None
            if self.project:
                # Check for GitLab or GitHub integration
                if hasattr(self.project, 'gitlab_project_id') and self.project.gitlab_project_id:
                    provider = 'gitlab'
                    project_id = self.project.gitlab_project_id
                elif hasattr(self.project, 'github_repo_id') and self.project.github_repo_id:
                    provider = 'github'
                    project_id = self.project.github_repo_id
            
            for sha in unique_commits:
                self.linked_commits.append({
                    'sha': sha,
                    'provider': provider,
                    'project_id': project_id
                })
        
        self.has_commit_correlation = len(unique_commits) > 0
        
        # Detect metric correlation keywords using word boundaries to avoid false positives
        # e.g., "hang" should not match inside "changes"
        def has_keyword(text, patterns):
            """Check if any pattern matches as a whole word."""
            for pattern in patterns:
                # Use word boundary \b for whole word matching
                if re.search(r'\b' + re.escape(pattern) + r'\b', text, re.IGNORECASE):
                    return True
            return False
        
        # More specific patterns to reduce false positives
        memory_patterns = [
            'high memory', 'memory usage', 'memory leak', 'memory high',
            'out of memory', 'oom', 'heap', 'ram usage', 'memory pressure'
        ]
        cpu_patterns = [
            'high cpu', 'cpu usage', 'cpu spike', 'cpu high',
            'deadlock', 'infinite loop', 'thread hang', 'process hang'
        ]
        
        if has_keyword(desc_text, memory_patterns):
            self.has_metric_correlation = True
            self.metric_correlation_type = 'memory'
        elif has_keyword(desc_text, cpu_patterns):
            self.has_metric_correlation = True
            self.metric_correlation_type = 'cpu'
        else:
            self.has_metric_correlation = False
            self.metric_correlation_type = ''

    def _invalidate_dashboard_caches(self):
        """
        Invalidate dashboard caches when issue is saved/deleted.
        Phase 2: Cache invalidation for dashboard performance.

        Note: cache_page generates cache keys based on full URL + query params.
        Precise invalidation is challenging without knowing all query combinations.
        Current strategy: Rely on TTL (5-15 min) for freshness.
        Future improvement: Switch to manual cache.get/set with predictable keys.
        """
        from django.core.cache import cache

        # Attempt to invalidate cache_page entries by pattern
        # This is a best-effort approach; TTL provides actual freshness guarantee
        org_id = None
        if self.project and self.project.organisation:
            org_id = self.project.organisation.id
        elif self.batch and self.batch.organisation:
            org_id = self.batch.organisation.id

        if org_id:
            # Note: cache_page keys are like "views.decorators.cache.cache_page.<md5(url)>"
            # We can't easily predict them, so we rely on TTL expiration
            # This method is a placeholder for future manual cache key invalidation
            logger.debug(f"Issue saved/deleted for org {org_id}, cache will refresh within TTL")

    def delete(self, *args, **kwargs):
        """Override delete to invalidate dashboard caches."""
        # Invalidate caches before deletion (while we still have access to relations)
        self._invalidate_dashboard_caches()
        super().delete(*args, **kwargs)

    @staticmethod
    def normalize_component(name):
        """Normalize component name for consistent fingerprinting"""
        if not name:
            return ''
        return name.lower().strip().replace('-', '_').replace(' ', '_')
    
    @staticmethod
    def normalize_error_target(target):
        """Light normalization for the STORED ``error_target`` field.

        RCA audit finding #3, 2026-09-19. Previously this normaliser
        did double duty — it collapsed volatile parts (ports, UUIDs,
        pids, 4-digit ids) to ``<id>`` / ``<uuid>`` placeholders so
        two errors from the same class would fingerprint identically.
        The same normalised value was then stored on the row, which
        meant an operator triaging an incident saw
        ``error_target='redis:<id>'`` instead of the actual
        ``redis:6379`` port they needed to grep for.

        Fix: this method now does trim + lowercase + path-strip only,
        preserving the human-readable identifier. The
        ``_signature_normalize_error_target`` sibling below produces
        the aggressive form for fingerprint hashing so dedup still
        collapses ``redis:6379`` and ``redis:6380`` into one issue.
        """
        if not target:
            return ''
        target = target.strip("'\"`:;,. ")
        target = target.lower()
        if '/' in target:
            target = target.split('/')[-1]
        return target[:100]

    @staticmethod
    def _signature_normalize_error_target(target):
        """Aggressive normalisation used ONLY for fingerprint hashing.

        Kept private (leading underscore) because callers outside the
        fingerprint code should use :meth:`normalize_error_target` —
        which preserves the human-readable identifier for storage.
        """
        if not target:
            return ''
        import re
        target = Issue.normalize_error_target(target)
        target = re.sub(
            r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            '<uuid>', target,
        )
        target = re.sub(r'\d{4,}', '<id>', target)  # 4+ digit numbers → <id>
        return target[:100]
    
    @staticmethod
    def _serialize_reasoning(reasoning):
        """Normalise the AI's reasoning chain to a single text string.

        The prompt asks for an array of step strings. Older prompts and
        fallback adapters may return a single string or None. We accept
        either, return None when there is nothing to show, and otherwise
        join the steps as "1. step ... 2. step ..." so the frontend can
        render an ordered list without parsing JSON.
        """
        if not reasoning:
            return None
        if isinstance(reasoning, str):
            text = reasoning.strip()
            return text or None
        if isinstance(reasoning, (list, tuple)):
            cleaned = [str(step).strip() for step in reasoning if str(step).strip()]
            if not cleaned:
                return None
            return '\n'.join(f"{idx}. {step}" for idx, step in enumerate(cleaned, start=1))
        return None

    @staticmethod
    def _normalize_confidence(confidence):
        """Coerce AI confidence to one of HIGH / MEDIUM / LOW / UNKNOWN."""
        if not confidence:
            return 'UNKNOWN'
        upper = str(confidence).upper().strip()
        if upper in ('HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'):
            return upper
        # Be forgiving of "med", "hi", etc.
        if upper.startswith('HI'):
            return 'HIGH'
        if upper.startswith('MED'):
            return 'MEDIUM'
        if upper.startswith('LO'):
            return 'LOW'
        return 'UNKNOWN'

    @staticmethod
    def validate_error_class(error_class):
        """Validate error_class against allowed list; preserve non-standard values for fingerprint diversity."""
        if not error_class:
            return 'OTHER'
        valid_classes = [ec[0] for ec in Issue.ERROR_CLASSES]
        upper = error_class.upper().strip()
        if upper in valid_classes:
            return upper
        # Preserve AI's classification (uppercased, truncated) for fingerprint diversity
        # Only fall back to OTHER for empty/whitespace values
        if upper and len(upper) <= 50:
            logger.info(f"Non-standard error_class from AI: '{error_class}', preserving as '{upper}'")
            return upper
        logger.warning(f"Invalid error_class from AI: '{error_class}', falling back to OTHER")
        return 'OTHER'
    
    FINGERPRINT_VERSION = 'v4'

    @staticmethod
    def generate_fingerprint(issue_type, scope, project_name, component, environment='',
                             error_class='OTHER', error_target=''):
        """
        Generate stable fingerprint for deduplication.
        v4: Versioned prefix, issue-type-aware empty component fallback.
        """
        import hashlib
        normalized_component = Issue.normalize_component(component) or f'_NO_COMPONENT_{issue_type}'
        # Fingerprint uses the aggressive normaliser (audit finding #3):
        # port/pid/uuid literals collapse to placeholders so
        # ``redis:6379`` and ``redis:6380`` hash to the same signature.
        # The row still STORES ``normalize_error_target`` for display.
        normalized_target = Issue._signature_normalize_error_target(error_target)

        parts = [
            issue_type,
            scope,
            project_name or 'NO_PROJECT',
            normalized_component,
            environment or 'UNKNOWN',
            error_class or 'OTHER',
            normalized_target or 'GENERIC',
        ]
        content = "|".join(parts)
        raw_hash = hashlib.sha256(content.encode()).hexdigest()[:32]
        return f"{Issue.FINGERPRINT_VERSION}:{raw_hash}"

    @staticmethod
    def generate_legacy_fingerprint(issue_type, scope, project_name, component, environment='',
                                     error_class='OTHER', error_target=''):
        """Generate old-format fingerprint (no version prefix, old component fallback)."""
        import hashlib
        normalized_component = Issue.normalize_component(component) or 'UNKNOWN'
        normalized_target = Issue._signature_normalize_error_target(error_target)
        parts = [
            issue_type, scope, project_name or 'NO_PROJECT',
            normalized_component, environment or 'UNKNOWN',
            error_class or 'OTHER', normalized_target or 'GENERIC',
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]
    
    #: How long a critical issue must stay quiet before it pages again.
    CRITICAL_REPAGE_AFTER = timedelta(hours=1)

    def is_newly_critical(self, batch):
        """True when ``batch`` saw this issue as CRITICAL and it had no
        CRITICAL sighting in the hour before: a new issue, one that just
        escalated, or one back after going quiet.

        The on-call ``critical_issue`` event uses it, so an ongoing incident
        re-reported by every 5-minute batch pages once, not every 5 minutes
        (found by the journey suite).
        """
        this = self.occurrences.filter(batch=batch).first()
        if this is None or (this.severity or self.severity or '').upper() != 'CRITICAL':
            return False
        return not self.occurrences.filter(
            severity__iexact='CRITICAL',
            seen_at__lt=this.seen_at,
            seen_at__gte=this.seen_at - self.CRITICAL_REPAGE_AFTER,
        ).exclude(pk=this.pk).exists()

    def record_occurrence(self, batch, severity=None):
        """Record that ``batch`` reported this issue, and make it the latest.

        Every sighting is appended to ``IssueOccurrence`` so a batch's history
        survives later recurrences; ``self.batch`` follows the newest sighting
        because "where was this last seen" is still worth answering cheaply.

        Replaces ``move_to_batch``, which decremented the previous batch's
        ``issue_count`` on every recurrence. That is why a batch's issue list
        emptied out over time: each later batch that re-reported an issue took
        it away from the batch that had originally found it.
        """
        if batch is None:
            return

        IssueOccurrence.objects.get_or_create(
            issue=self, batch=batch,
            defaults={'severity': severity or self.severity},
        )

        if self.batch_id != batch.id:
            self.batch = batch
            self.save(update_fields=['batch'])

    @classmethod
    def find_or_create_deduplicated(cls, issue_data, batch, project, environment):
        """
        Tiered matching for deduplication:
        1. Exact fingerprint match
        2. INFRASTRUCTURE promotion (metrics-only followed by logs+metrics)
        Returns (issue, created)

        Thread-safe with select_for_update() to prevent race conditions in concurrent
        batch processing. Uses atomic F() expressions for occurrence_count updates.

        A partial unique constraint (fingerprint, project) WHERE status IN ('OPEN', 'MUTED')
        acts as a DB-level safety net. If two threads race past select_for_update (both
        finding no existing row), the loser gets IntegrityError and retries by looking
        up the winner's row.
        """
        from django.utils import timezone
        from datetime import timedelta
        from django.db import transaction, IntegrityError
        from django.db.models import F
        from org_settings.models import IssueSettings

        issue_type = issue_data.get('issue_type', 'OTHER')
        scope = issue_data.get('scope', 'SERVICE')
        component = issue_data.get('component', '')
        severity = issue_data.get('severity', 'UNKNOWN')

        # v3: Extract and validate AI classification fields
        error_class = cls.validate_error_class(issue_data.get('error_class', 'OTHER'))
        error_target = cls.normalize_error_target(issue_data.get('error_target', ''))

        # Generate fingerprint with v3 fields
        project_name = project.name if project else ''
        fingerprint = cls.generate_fingerprint(
            issue_type, scope, project_name, component, environment,
            error_class=error_class, error_target=error_target
        )

        # Get dedup settings
        dedup_enabled = True
        dedup_window_days = 7
        if project and project.organisation:
            try:
                settings = IssueSettings.objects.get(organisation=project.organisation)
                dedup_enabled = settings.dedup_enabled
                dedup_window_days = settings.dedup_window_days
            except IssueSettings.DoesNotExist:
                pass

        if not dedup_enabled:
            # Derive organisation
            org = None
            if project and hasattr(project, 'organisation'):
                org = project.organisation
            elif batch and batch.organisation:
                org = batch.organisation
            # Create new issue without dedup (no locking needed)
            issue = cls.objects.create(
                batch=batch,
                project=project,
                organisation=org,
                affected_services=cls.normalize_affected_services(
                    issue_data.get('affected_services'), component),
                issue_type=issue_type,
                scope=scope,
                component=component,
                environment=environment,
                severity=severity,
                description=issue_data.get('description', ''),
                recommendation=issue_data.get('recommended_action', ''),
                root_cause=issue_data.get('root_cause', ''),
                reasoning=cls._serialize_reasoning(issue_data.get('reasoning')),
                confidence=cls._normalize_confidence(issue_data.get('confidence')),
                fingerprint=fingerprint,
                error_class=error_class,
                error_target=error_target,
                status='OPEN'
            )
            return issue, True

        # Dedup window cutoff
        cutoff = None
        if dedup_window_days > 0:
            cutoff = timezone.now() - timedelta(days=dedup_window_days)

        issue, created = cls._find_or_create_with_retry(
            issue_data=issue_data,
            batch=batch,
            project=project,
            environment=environment,
            fingerprint=fingerprint,
            issue_type=issue_type,
            scope=scope,
            component=component,
            severity=severity,
            error_class=error_class,
            error_target=error_target,
            cutoff=cutoff,
            project_name=project_name,
        )
        # A recurring issue keeps every service it has affected so far.
        services = cls.normalize_affected_services(
            list(issue.affected_services or []) + cls.normalize_affected_services(
                issue_data.get('affected_services'), issue.component),
            issue.component)
        if services != (issue.affected_services or []):
            issue.affected_services = services
            issue.save(update_fields=['affected_services'])
        return issue, created

    @property
    def effective_root_cause(self):
        """The team's root cause when they gave one on resolve, else the AI's."""
        return (self.resolution_root_cause or '').strip() or (self.root_cause or '').strip()

    @property
    def effective_fix(self):
        return (self.resolution_fix or '').strip() or (self.recommendation or '').strip()

    @staticmethod
    def normalize_affected_services(value, component=''):
        """A sorted list of distinct service names, without ``component``.

        The model sends a list of names; tolerate a comma-separated string.
        """
        if isinstance(value, str):
            value = value.split(',')
        if not isinstance(value, (list, tuple)):
            return []
        names = {str(v).strip()[:100] for v in value if isinstance(v, (str, int)) and str(v).strip()}
        names.discard(component or '')
        return sorted(names, key=str.lower)[:50]

    @classmethod
    def _find_or_create_with_retry(cls, *, issue_data, batch, project, environment,
                                    fingerprint, issue_type, scope, component, severity,
                                    error_class, error_target, cutoff, project_name,
                                    _retries=0):
        """
        Inner method that performs the actual find-or-create inside a transaction.
        On IntegrityError (concurrent insert with same fingerprint), retries once
        to find the winning row and update it instead.
        """
        from django.utils import timezone
        from django.db import transaction, IntegrityError
        from django.db.models import F

        MAX_RETRIES = 2

        try:
            with transaction.atomic():
                # Tier 1: Check both v4 and legacy fingerprints
                legacy_fp = cls.generate_legacy_fingerprint(
                    issue_type, scope, project_name, component, environment,
                    error_class=error_class, error_target=error_target
                )
                base_query = cls.objects.filter(
                    models.Q(fingerprint=fingerprint) | models.Q(fingerprint=legacy_fp)
                )
                if project:
                    base_query = base_query.filter(project=project)
                else:
                    # C1 fix: filter by organisation when project is NULL
                    org = batch.organisation if batch else None
                    base_query = base_query.filter(project__isnull=True, organisation=org)
                if cutoff:
                    base_query = base_query.filter(created_at__gte=cutoff)

                existing = (
                    base_query.filter(status__in=['OPEN', 'MUTED'])
                    .select_for_update().first()
                )
                if not existing:
                    # Check for RESOLVED issues that should be reopened
                    existing = (
                        base_query.filter(status='RESOLVED')
                        .select_for_update().first()
                    )

                # Tier 2: INFRASTRUCTURE promotion
                if not existing and scope == 'SERVICE' and component:
                    infra_fp = cls.generate_fingerprint(
                        issue_type, 'INFRASTRUCTURE', project_name, 'INFRASTRUCTURE', environment,
                        error_class=error_class, error_target=error_target
                    )
                    infra_legacy_fp = cls.generate_legacy_fingerprint(
                        issue_type, 'INFRASTRUCTURE', project_name, 'INFRASTRUCTURE', environment,
                        error_class=error_class, error_target=error_target
                    )
                    infra_query = cls.objects.filter(
                        models.Q(fingerprint=infra_fp) | models.Q(fingerprint=infra_legacy_fp),
                        status__in=['OPEN', 'MUTED']
                    )
                    if project:
                        infra_query = infra_query.filter(project=project)
                    if cutoff:
                        infra_query = infra_query.filter(created_at__gte=cutoff)

                    infra_match = infra_query.select_for_update().first()
                    if infra_match:
                        cls.objects.filter(pk=infra_match.pk).update(
                            component=component,
                            scope=scope,
                            fingerprint=fingerprint,
                            occurrence_count=F('occurrence_count') + 1,
                            last_seen_at=timezone.now()
                        )
                        infra_match.refresh_from_db()
                        infra_match.record_occurrence(batch, severity)
                        return infra_match, False

                if existing:
                    update_fields = {
                        'occurrence_count': F('occurrence_count') + 1,
                        'last_seen_at': timezone.now()
                    }

                    if existing.status == 'RESOLVED':
                        update_fields['status'] = 'OPEN'

                    # H3: Upgrade legacy fingerprint to v4
                    if not existing.fingerprint.startswith('v4:'):
                        update_fields['fingerprint'] = fingerprint

                    severity_order = {'INFO': 0, 'UNKNOWN': 1, 'WARNING': 2, 'CRITICAL': 3}
                    if severity_order.get(severity, 0) > severity_order.get(existing.severity, 0):
                        update_fields['severity'] = severity

                    cls.objects.filter(pk=existing.pk).update(**update_fields)
                    existing.refresh_from_db()
                    existing.record_occurrence(batch, severity)
                    return existing, False

                # Derive organisation for new issue
                org = None
                if project and hasattr(project, 'organisation'):
                    org = project.organisation
                elif batch and batch.organisation:
                    org = batch.organisation

                # Create new issue — the unique constraint is the safety net
                issue = cls.objects.create(
                    batch=batch,
                    project=project,
                    organisation=org,
                    issue_type=issue_type,
                    scope=scope,
                    component=component,
                    environment=environment,
                    severity=severity,
                    description=issue_data.get('description', ''),
                    recommendation=issue_data.get('recommended_action', ''),
                    root_cause=issue_data.get('root_cause', ''),
                    reasoning=cls._serialize_reasoning(issue_data.get('reasoning')),
                    confidence=cls._normalize_confidence(issue_data.get('confidence')),
                    fingerprint=fingerprint,
                    error_class=error_class,
                    error_target=error_target,
                    status='OPEN'
                )
                # Record the sighting for the batch that created it, so a
                # brand-new issue is attributable to its batch on exactly the
                # same basis as a recurrence.
                issue.record_occurrence(batch, severity)
                return issue, True

        except IntegrityError:
            # Another thread created the same issue concurrently.
            # Retry to find and update the winning row.
            if _retries < MAX_RETRIES:
                logger.info(
                    f"IntegrityError on fingerprint {fingerprint[:12]}..., "
                    f"retrying ({_retries + 1}/{MAX_RETRIES})"
                )
                return cls._find_or_create_with_retry(
                    issue_data=issue_data,
                    batch=batch,
                    project=project,
                    environment=environment,
                    fingerprint=fingerprint,
                    issue_type=issue_type,
                    scope=scope,
                    component=component,
                    severity=severity,
                    error_class=error_class,
                    error_target=error_target,
                    cutoff=cutoff,
                    project_name=project_name,
                    _retries=_retries + 1,
                )
            raise




class IssueOccurrence(models.Model):
    """One sighting of an issue in one batch.

    ``Issue.batch`` is a single FK, so an issue can only point at ONE batch —
    and ``move_to_batch`` repoints it to the newest one on every recurrence,
    decrementing the previous batch's ``issue_count`` as it goes. The effect is
    that a batch's issue list shrinks over time and eventually empties: the
    batch detail page answers "which issues are still most recently seen here?"
    while appearing to answer "what did this analysis find?".

    Measured on the chaos-RCA run: of 25 analysed batches, 17 listed fewer
    issues than their own stored analysis reported, and two listed none at all
    despite having reported one. The reports themselves were correct — the
    history had been moved out from under them.

    Recurrence is many-to-many by nature (one issue occurs in many batches),
    so it gets a table. ``Issue.batch`` stays as the most-recent pointer, which
    is genuinely useful for "where was this last seen"; everything that means
    "what did this batch report" reads through here instead.
    """

    issue = models.ForeignKey(
        'Issue', on_delete=models.CASCADE, related_name='occurrences',
    )
    batch = models.ForeignKey(
        AIAnalyzedBatch, on_delete=models.CASCADE, related_name='issue_occurrences',
    )
    # When this batch reported the issue. Distinct from Issue.created_at, which
    # is the first sighting across all batches.
    seen_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Severity as reported by THIS batch. An issue's severity can be revised on
    # a later sighting; keeping the per-sighting value means a historical batch
    # still shows what it actually said at the time.
    severity = models.CharField(max_length=20, blank=True, null=True)

    class Meta:
        # One row per (issue, batch): a batch reporting the same issue twice in
        # one analysis is a duplicate, not two occurrences.
        unique_together = (('issue', 'batch'),)
        indexes = [
            models.Index(fields=['batch', 'seen_at']),
        ]
        ordering = ['-seen_at']

    def __str__(self):
        return f'Issue {self.issue_id} in batch {self.batch_id}'


class RedactionReport(models.Model):
    """
    Stores redaction reports for compliance and UI display.
    
    Tracks what sensitive data was detected and masked before sending to AI.
    Used for:
    - Compliance auditing
    - UI display of protection status
    - Statistics and reporting
    """
    
    batch = models.ForeignKey(
        AIAnalyzedBatch, 
        on_delete=models.CASCADE, 
        related_name='redaction_reports',
        null=True,
        blank=True
    )
    
    # Optional link to project for non-batch redactions (e.g., chat)
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='redaction_reports'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Source type
    source_type = models.CharField(
        max_length=20,
        choices=[
            ('logs', 'Log Analysis'),
            ('code_change', 'Code Change'),
            ('chat', 'Chat Message'),
            ('other', 'Other'),
        ],
        default='logs'
    )
    
    # Statistics
    total_items_redacted = models.IntegerField(default=0)
    critical_count = models.IntegerField(default=0)
    high_count = models.IntegerField(default=0)
    medium_count = models.IntegerField(default=0)
    
    # Detailed findings (JSON)
    findings_summary = models.JSONField(default=dict)
    
    # Size tracking
    original_size_bytes = models.IntegerField(default=0)
    redacted_size_bytes = models.IntegerField(default=0)
    
    # User consent tracking (for chat messages)
    user_consented = models.BooleanField(
        default=False,
        help_text="True if user chose to send anyway despite warning"
    )
    
    class Meta:
        db_table = 'redaction_reports'
        ordering = ['-created_at']
        verbose_name = "Redaction Report"
        verbose_name_plural = "Redaction Reports"
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['source_type']),
        ]
    
    def __str__(self):
        if self.batch:
            return f"Redaction Report for {self.batch.batch_id}"
        return f"Redaction Report ({self.source_type}) - {self.created_at}"
    
    @property
    def total_by_severity(self):
        """Get total counts by severity."""
        return {
            'critical': self.critical_count,
            'high': self.high_count,
            'medium': self.medium_count,
        }
    
    @classmethod
    def create_from_findings(cls, findings_summary, batch=None, project=None, source_type='logs', original_size=0, redacted_size=0):
        """
        Create a RedactionReport from a findings summary.
        
        Args:
            findings_summary: Dict from DataRedactionService.get_summary()
            batch: Optional AIAnalyzedBatch instance
            project: Optional Project instance
            source_type: Type of source data
            original_size: Original text size in bytes
            redacted_size: Redacted text size in bytes
        """
        return cls.objects.create(
            batch=batch,
            project=project,
            source_type=source_type,
            total_items_redacted=findings_summary.get('total_count', 0),
            critical_count=findings_summary.get('critical_count', 0),
            high_count=findings_summary.get('high_count', 0),
            medium_count=findings_summary.get('medium_count', 0),
            findings_summary=findings_summary,
            original_size_bytes=original_size,
            redacted_size_bytes=redacted_size,
        )


class AuditLog(models.Model):
    """Tracks important user actions for compliance and security"""
    
    ACTION_TYPES = [
        ('LOGIN', 'User Login'),
        ('LOGIN_FAILED', 'Failed Login Attempt'),
        ('LOGOUT', 'User Logout'),
        ('PASSWORD_CHANGE', 'Password Changed'),
        ('SETTINGS_CHANGE', 'Settings Changed'),
        ('SERVICE_CREATE', 'Service Created'),
        ('SERVICE_UPDATE', 'Service Updated'),
        ('SERVICE_DELETE', 'Service Deleted'),
        ('BATCH_DELETE', 'Batch Deleted'),
        ('BATCH_CLEANUP', 'Batch Auto-Cleanup'),
        ('TEAM_INVITE', 'Team Member Invited'),
        ('TEAM_REMOVE', 'Team Member Removed'),
        ('TEAM_ROLE_CHANGE', 'Team Role Changed'),
        ('AI_MODEL_CHANGE', 'AI Model Changed'),
        ('NOTIFICATION_TEST', 'Notification Test Sent'),
        ('EXPORT_DATA', 'Data Exported'),
        ('ACCOUNT_DELETE', 'User Account Deleted (GDPR)'),
        ('ORG_DELETE', 'Organisation Deleted (GDPR)'),
        ('INVESTIGATION_RUN', 'Investigation Started'),
        ('ACCESS_DENIED', 'Access Denied'),
    ]
    
    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='audit_logs'
    )
    user = models.ForeignKey(
        'Users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs'
    )
    action = models.CharField(max_length=50, choices=ACTION_TYPES, db_index=True)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        db_table = 'audit_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organisation', '-created_at']),
            models.Index(fields=['action', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        user_str = self.user.email if self.user else 'System'
        return f"{self.action} by {user_str} at {self.created_at}"


class ProjectEnvironmentState(models.Model):
    """Rolling state for Sentinel — tracks baselines and trends per project+environment."""

    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        related_name='environment_states',
    )
    environment = models.ForeignKey(
        'Projects.ProjectEnvironment',
        on_delete=models.CASCADE,
        related_name='sentinel_states',
    )
    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='environment_states',
    )

    # Rolling trend arrays (last N batch values)
    error_counts = models.JSONField(default=list)
    memory_avg = models.JSONField(default=list)
    cpu_avg = models.JSONField(default=list)
    log_volume = models.JSONField(default=list)

    # Baselines (exponential moving averages)
    baseline_error_rate = models.FloatField(default=0)
    baseline_memory = models.FloatField(default=0)
    baseline_cpu = models.FloatField(default=0)
    baseline_stddev_memory = models.FloatField(default=1)
    baseline_stddev_cpu = models.FloatField(default=1)

    # Warning/error log patterns seen recently: signature -> last-seen ISO
    # timestamp. Sentinel's "new error pattern" check reads this; it is not
    # the same hash as Issue.fingerprint (that one keys AI-found issues).
    known_log_patterns = models.JSONField(default=dict)

    # Deployment tracking
    last_deploy_sha = models.CharField(max_length=100, blank=True, default='')
    last_deploy_at = models.DateTimeField(null=True, blank=True)

    # AI analysis tracking
    last_ai_analysis_at = models.DateTimeField(null=True, blank=True)
    last_ai_summary = models.TextField(blank=True, default='')
    batches_since_last_ai = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('project', 'environment')
        verbose_name = 'Project Environment State'
        verbose_name_plural = 'Project Environment States'

    def __str__(self):
        return f"State: {self.project.name} / {self.environment.name}"


class RetentionPolicy(models.Model):
    """Organization-level data retention and auto-cleanup policies"""
    
    organisation = models.OneToOneField(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='retention_policy'
    )
    
    # Auto-cleanup settings
    auto_cleanup_enabled = models.BooleanField(default=False)
    
    RETENTION_CHOICES = [
        (7, '7 days'),
        (14, '14 days'),
        (30, '30 days'),
        (60, '60 days'),
        (90, '90 days'),
        (180, '6 months'),
        (365, '1 year'),
    ]
    retention_days = models.IntegerField(
        choices=RETENTION_CHOICES,
        default=30
    )
    
    # Raw metric points are 93% of a batch's stored payload (measured:
    # 69 KB of 74 KB) and serve only the batch metrics chart. The analysis,
    # the issues and `metrics_summary` — the per-service stats and anomalies the
    # AI actually reasoned over — are the remaining 7%.
    #
    # Trimming the raw points is therefore cheap to lose and expensive to keep:
    # at a ten-minute batch interval that payload accrues roughly 10 MB per day
    # per project, forever, because `auto_cleanup_enabled` defaults to False and
    # the only existing cleanup deletes whole batches — all-or-nothing, taking
    # the analysis with it.
    #
    # 0 means keep raw points as long as the batch itself.
    RAW_METRICS_RETENTION_CHOICES = [
        (0, 'Keep as long as the batch'),
        (7, '7 days'),
        (14, '14 days'),
        (30, '30 days'),
        (90, '90 days'),
    ]
    raw_metrics_retention_days = models.IntegerField(
        choices=RAW_METRICS_RETENTION_CHOICES,
        default=30,
        help_text=(
            'Drop raw metric points from batches older than this, keeping the '
            'analysis, the issues and the metric summary. Only the batch '
            'metrics chart loses detail. 0 keeps them for the batch lifetime.'
        ),
    )

    FREQUENCY_CHOICES = [
        ('daily', 'Daily (midnight)'),
        ('weekly', 'Weekly (Sunday midnight)'),
        ('monthly', 'Monthly (1st of month)'),
    ]
    cleanup_frequency = models.CharField(
        max_length=20,
        choices=FREQUENCY_CHOICES,
        default='weekly'
    )
    
    # Audit log retention (separate from data retention)
    AUDIT_RETENTION_CHOICES = [
        (30, '30 days'),
        (90, '90 days'),
        (365, '1 year'),
        (0, 'Forever'),
    ]
    audit_log_retention_days = models.IntegerField(
        choices=AUDIT_RETENTION_CHOICES,
        default=90
    )
    
    # Batch generation interval (per-org override)
    BATCH_INTERVAL_CHOICES = [
        (5, '5 minutes'),
        (10, '10 minutes'),
        (15, '15 minutes'),
        (20, '20 minutes'),
        (30, '30 minutes'),
        (45, '45 minutes'),
        (60, '1 hour'),
        (120, '2 hours'),
        (240, '4 hours'),
        (360, '6 hours'),
        (720, '12 hours'),
    ]
    batch_generation_interval = models.IntegerField(
        choices=BATCH_INTERVAL_CHOICES,
        default=15,
        help_text='How often to generate log/metric batches (in minutes)'
    )

    # Tracking
    last_cleanup_at = models.DateTimeField(null=True, blank=True)
    last_cleanup_count = models.IntegerField(default=0)
    next_cleanup_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'retention_policies'
        verbose_name = 'Retention Policy'
        verbose_name_plural = 'Retention Policies'
    
    def __str__(self):
        return f"Retention Policy for {self.organisation.name}"

    def should_run_cleanup(self) -> bool:
        """Return True when the periodic auto-cleanup task should act.

        Called from ``Data.tasks.run_auto_retention_cleanup``. Was
        missing entirely — the task called ``policy.should_run_cleanup()``,
        got AttributeError, and the outer ``except Exception`` swallowed
        it silently, so no retention policy ever cleaned up anything.
        Found in E51.

        Semantics:
          * ``last_cleanup_at is None`` → yes, we've never run
          * ``cleanup_frequency='daily'``  → run if >23h since last
          * ``cleanup_frequency='weekly'`` → run if >6.5d since last
          * ``cleanup_frequency='monthly'`` → run if >29d since last

        Slightly-less-than-the-nominal interval so a cron with drift
        (a few seconds late from the scheduled time) still runs.
        """
        from django.utils import timezone
        if self.last_cleanup_at is None:
            return True
        elapsed = timezone.now() - self.last_cleanup_at
        thresholds_hours = {'daily': 23, 'weekly': 24 * 6.5,
                            'monthly': 24 * 29}
        min_hours = thresholds_hours.get(self.cleanup_frequency, 24 * 6.5)
        return elapsed.total_seconds() >= min_hours * 3600


class AlertEvent(models.Model):
    """
    An inbound alert from Alertmanager / Grafana Alerts / Datadog Monitors
    (Item #13). Persisted for audit + to link the on-demand analysis
    batch back to what triggered it.

    Design:

    * Store the raw payload so support can debug parsing regressions
      without asking the user to re-emit the alert.
    * Enum ``source`` avoids accidental provider mislabeling.
    * ``triggered_batch`` FK is populated by the on-demand pipeline
      (Item #14) once the alert-scoped batch has been created.
    * Idempotency: ``external_id`` + ``source`` uniqueness prevents a
      retry from Alertmanager (which retries aggressively) from
      triggering N duplicate analyses. If external_id is empty, we
      dedup on (source, alertname, service, environment, fingerprint).
    """

    SOURCE_CHOICES = [
        ('alertmanager', 'Prometheus Alertmanager'),
        ('grafana', 'Grafana Alerts'),
        ('datadog', 'Datadog Monitors'),
    ]

    STATE_CHOICES = [
        ('firing', 'Firing'),
        ('resolved', 'Resolved'),
        ('unknown', 'Unknown'),
    ]

    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='alert_events',
    )
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES)
    external_id = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Provider-supplied fingerprint / alert id. Empty when '
                  'the provider does not supply one.',
    )
    alertname = models.CharField(max_length=255)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default='firing')
    severity = models.CharField(max_length=32, blank=True, default='')
    service = models.CharField(max_length=255, blank=True, default='')
    environment = models.CharField(max_length=64, blank=True, default='')
    summary = models.TextField(blank=True, default='')

    # Raw provider payload — for debugging + reprocessing.
    raw_payload = models.JSONField(default=dict, blank=True)

    triggered_batch = models.ForeignKey(
        AIAnalyzedBatch,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='triggering_alerts',
    )

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'alert_events'
        indexes = [
            models.Index(fields=['organisation', '-received_at'], name='alert_org_received_idx'),
            models.Index(fields=['source', 'external_id'], name='alert_source_extid_idx'),
        ]
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.source}:{self.alertname} ({self.state})'


class Investigation(models.Model):
    """An analysis a user asked for: one scope, one time window, now.

    Runs the same batch pipeline as the scheduler, with three differences:
    Sentinel never skips it, it reads every log in the window (no dedup
    against earlier batches), and it does not page anyone through routing
    rules unless ``notify_routing`` is set.
    """
    STATUS_QUEUED = 'queued'
    STATUS_COLLECTING = 'collecting'
    STATUS_ANALYZING = 'analyzing'
    STATUS_DONE = 'done'
    STATUS_NO_DATA = 'no_data'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_QUEUED, 'Queued'),
        (STATUS_COLLECTING, 'Collecting data'),
        (STATUS_ANALYZING, 'Analyzing'),
        (STATUS_DONE, 'Done'),
        (STATUS_NO_DATA, 'No data in the window'),
        (STATUS_FAILED, 'Failed'),
    ]
    ACTIVE_STATUSES = (STATUS_QUEUED, STATUS_COLLECTING, STATUS_ANALYZING)

    MIN_WINDOW_MINUTES = 5
    MAX_WINDOW_HOURS = 6
    HINT_MAX_LENGTH = 500
    # An analysis that has not finished by then crashed without saying so.
    ANALYSIS_TIMEOUT_MINUTES = 15

    organisation = models.ForeignKey(
        'Organisations.Organisations', on_delete=models.CASCADE, related_name='investigations',
    )
    requested_by = models.ForeignKey(
        'Users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='investigations',
    )
    project = models.ForeignKey('Projects.Project', on_delete=models.CASCADE, related_name='investigations')
    environment = models.ForeignKey(
        'Projects.ProjectEnvironment', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    deployment = models.ForeignKey(
        'Projects.ProjectDeployment', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    # Service names to keep; empty means every registered service.
    services = models.JSONField(default=list, blank=True)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    hint = models.TextField(blank=True, default='')
    notify_routing = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_QUEUED, db_index=True)
    # Data points found per source: logs, metrics, traces, code_changes, cicd.
    counts = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=40, blank=True, default='')
    error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['organisation', '-created_at'])]

    def __str__(self):
        return f"Investigation {self.pk} ({self.project_id}, {self.status})"

    def finish(self, status, error_code='', error=''):
        self.status = status
        self.error_code = error_code
        self.error = error
        self.finished_at = timezone.now()
        self.save(update_fields=['status', 'error_code', 'error', 'finished_at'])

    def settle(self):
        """Bring an active run's status up to date before it is shown.

        The AI step runs in analyze_batch, which has many exits; reading the
        outcome off the batch keeps that task free of investigation logic.
        A run that stays active past the timeout crashed without saying so.
        """
        if self.status not in self.ACTIVE_STATUSES:
            return
        if self.status == self.STATUS_ANALYZING:
            batch = (AIAnalyzedBatch.objects.filter(investigation=self)
                     .only('analyzed_at', 'data', 'model_name').first())
            if batch is not None and batch.analyzed_at is not None:
                err = (batch.data or {}).get('error') or {}
                if err:
                    code = err.get('error_code') or 'AI_FAILED'
                    self.finish(self.STATUS_FAILED,
                                'over_budget' if code == 'AI_BUDGET_EXCEEDED' else code.lower(),
                                err.get('error_message') or 'The AI analysis failed.')
                elif (batch.model_name or '').upper().startswith('SKIPPED'):
                    self.finish(self.STATUS_NO_DATA)
                elif (batch.model_name or '').upper().startswith('FAILED'):
                    self.finish(self.STATUS_FAILED, 'ai_failed', 'The AI analysis did not complete.')
                else:
                    self.finish(self.STATUS_DONE)
                return
        since = self.started_at or self.created_at
        if since and timezone.now() - since > timezone.timedelta(minutes=self.ANALYSIS_TIMEOUT_MINUTES):
            self.finish(self.STATUS_FAILED, 'timeout',
                        'The investigation did not finish. Try again, or check the worker logs.')
