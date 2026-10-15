# notifications/models.py
"""
Notification Models for Multi-Tenant Email System

This module provides:
- Notification: In-app notification records
- UserNotificationPreference: Per-user channel and timing preferences
- ProjectSubscription: Explicit opt-in to project notifications
- NotificationQueue: Pending notifications for digest/retry
- EscalationRule: Escalation chains for unacknowledged issues
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class Notification(models.Model):
    """In-app notification record for a user."""
    
    NOTIFICATION_TYPES = [
        ('batch_created', 'Batch Created'),
        ('critical_issue', 'Critical Issue'),
        ('warning_issue', 'Warning Issue'),
        ('analysis_failed', 'Analysis Failed'),
        ('escalation', 'Escalation Alert'),
        ('digest', 'Digest Summary'),
        ('investigation_done', 'Investigation Finished'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    subject = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    notification_type = models.CharField(max_length=50, choices=NOTIFICATION_TYPES)
    batch_id = models.CharField(max_length=100, null=True, blank=True)
    
    # Link to issue for acknowledgment tracking
    issue = models.ForeignKey(
        'Data.Issue',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"{self.notification_type} - {self.user.email}"


class UserNotificationPreference(models.Model):
    """
    Per-user notification preferences.
    Controls channels, severity filters, digest timing, and quiet hours.
    """
    
    DIGEST_CHOICES = [
        ('immediate', 'Immediate'),
        ('hourly', 'Hourly Digest'),
        ('daily', 'Daily Digest'),
        ('weekly', 'Weekly Summary'),
    ]
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    # Channel toggles
    email_enabled = models.BooleanField(
        default=True,
        help_text='Receive email notifications'
    )
    in_app_enabled = models.BooleanField(
        default=True,
        help_text='Receive in-app notifications'
    )
    
    # Severity filters (global defaults, overridable per-subscription)
    notify_critical = models.BooleanField(default=True)
    notify_warning = models.BooleanField(default=True)
    notify_info = models.BooleanField(default=False)
    
    # Digest preferences
    digest_frequency = models.CharField(
        max_length=20,
        choices=DIGEST_CHOICES,
        default='immediate',
        help_text='How often to receive notification summaries'
    )
    
    # Quiet hours (local time based on timezone)
    quiet_hours_enabled = models.BooleanField(
        default=False,
        help_text='Suppress notifications during quiet hours'
    )
    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        help_text='Start of quiet period (e.g., 22:00)'
    )
    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        help_text='End of quiet period (e.g., 08:00)'
    )
    timezone = models.CharField(
        max_length=50,
        default='UTC',
        help_text='Timezone for quiet hours calculation'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'User Notification Preference'
        verbose_name_plural = 'User Notification Preferences'
    
    def __str__(self):
        return f"NotificationPrefs for {self.user.email}"
    
    def is_quiet_hours_active(self):
        """Check if current time is within quiet hours."""
        if not self.quiet_hours_enabled or not self.quiet_hours_start or not self.quiet_hours_end:
            return False
        
        try:
            import pytz
            tz = pytz.timezone(self.timezone)
            now = timezone.now().astimezone(tz).time()
            
            start = self.quiet_hours_start
            end = self.quiet_hours_end
            
            # Handle overnight quiet hours (e.g., 22:00 - 08:00)
            if start > end:
                return now >= start or now <= end
            else:
                return start <= now <= end
        except Exception:
            return False
    
    @classmethod
    def get_or_create_for_user(cls, user):
        """Get or create preferences for a user with role-based defaults."""
        prefs, created = cls.objects.get_or_create(
            user=user,
            defaults={
                'notify_critical': True,
                'notify_warning': user.role in ('admin', 'user'),
                'notify_info': False,
                'email_enabled': user.role == 'admin',
            }
        )
        return prefs


class ProjectSubscription(models.Model):
    """
    Explicit opt-in subscription to project notifications.
    Users must subscribe to receive notifications for a project.
    """
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='project_subscriptions'
    )
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        related_name='notification_subscribers'
    )
    
    # Severity overrides (null = use global preference)
    notify_critical = models.BooleanField(default=True)
    notify_warning = models.BooleanField(default=True)
    notify_info = models.BooleanField(default=False)
    
    # Channel override (null = use global preference)
    email_override = models.BooleanField(
        null=True,
        blank=True,
        help_text='Override email setting for this project (null=use global)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('user', 'project')
        verbose_name = 'Project Subscription'
        verbose_name_plural = 'Project Subscriptions'
        indexes = [
            models.Index(fields=['project', 'notify_critical']),
        ]
    
    def __str__(self):
        return f"{self.user.email} → {self.project.name}"
    
    def should_notify_for_severity(self, severity):
        """Check if this subscription covers the given severity."""
        severity_map = {
            'CRITICAL': self.notify_critical,
            'WARNING': self.notify_warning,
            'INFO': self.notify_info,
        }
        return severity_map.get(severity.upper(), False)


class NotificationQueue(models.Model):
    """
    Queue for pending/scheduled notifications.
    Used for digest batching, retry logic, and audit trail.
    """
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('queued_for_digest', 'Queued for Digest'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('suppressed', 'Suppressed'),
    ]
    
    CHANNEL_CHOICES = [
        ('email', 'Email'),
        ('slack', 'Slack'),
        ('teams', 'Microsoft Teams'),
        ('in_app', 'In-App'),
    ]
    
    SUPPRESSION_REASONS = [
        ('quiet_hours', 'Quiet Hours Active'),
        ('muted_issue', 'Issue Muted'),
        ('user_unsubscribed', 'User Not Subscribed'),
        ('severity_filtered', 'Severity Below Threshold'),
        ('duplicate', 'Duplicate Notification'),
        ('channel_disabled', 'Channel Disabled'),
    ]
    
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notification_queue'
    )
    issue = models.ForeignKey(
        'Data.Issue',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='queued_notifications'
    )
    batch = models.ForeignKey(
        'Data.AIAnalyzedBatch',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='queued_notifications'
    )
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='queued_notifications'
    )
    
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    severity = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True
    )
    suppression_reason = models.CharField(
        max_length=50,
        choices=SUPPRESSION_REASONS,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text='When to send (for digests)'
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'channel', '-created_at']),
            models.Index(fields=['user', 'status', 'scheduled_for']),
        ]
        verbose_name = 'Notification Queue Entry'
        verbose_name_plural = 'Notification Queue'
    
    def __str__(self):
        return f"{self.channel}:{self.status} - {self.user.email}"
    
    def mark_sent(self):
        """Mark notification as successfully sent."""
        self.status = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])
    
    def mark_failed(self, error_message):
        """Mark notification as failed with error details."""
        self.status = 'failed'
        self.retry_count += 1
        self.error_message = str(error_message)[:1000]
        self.save(update_fields=['status', 'retry_count', 'error_message'])
    
    def mark_suppressed(self, reason):
        """Mark notification as suppressed with reason."""
        self.status = 'suppressed'
        self.suppression_reason = reason
        self.save(update_fields=['status', 'suppression_reason'])


class EscalationRule(models.Model):
    """
    Escalation rules using role hierarchy.
    Unacknowledged critical issues escalate: user → admin → org admins.
    """
    
    SEVERITY_CHOICES = [
        ('CRITICAL', 'Critical'),
        ('WARNING', 'Warning'),
    ]
    
    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='escalation_rules'
    )
    project = models.ForeignKey(
        'Projects.Project',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text='If null, applies to all projects in org'
    )
    
    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_CHOICES,
        default='CRITICAL'
    )
    
    # Escalation timing (minutes after issue creation)
    level_1_delay_minutes = models.IntegerField(
        default=15,
        help_text='Minutes before escalating to admins'
    )
    level_2_delay_minutes = models.IntegerField(
        default=45,
        help_text='Minutes before escalating to org admins'
    )
    
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Escalation Rule'
        verbose_name_plural = 'Escalation Rules'
        unique_together = ('organisation', 'project', 'severity')
    
    def __str__(self):
        project_name = self.project.name if self.project else 'All Projects'
        return f"Escalation: {self.severity} in {project_name}"
    
    def get_level_1_targets(self, project):
        """
        Get Level 1 escalation targets using role hierarchy.
        Level 1: Project admins (users with admin role in the org).
        """
        return User.objects.filter(
            organisation=self.organisation,
            role='admin',
            is_active=True
        )
    
    def get_level_2_targets(self, project):
        """
        Get Level 2 escalation targets.
        Level 2: All org admins (final escalation).
        """
        return User.objects.filter(
            organisation=self.organisation,
            role='admin',
            is_active=True
        )
    
    @classmethod
    def get_rule_for_issue(cls, issue):
        """Get applicable escalation rule for an issue."""
        if not issue.project or not issue.project.organisation:
            return None
        
        # Try project-specific rule first, then org-wide
        rule = cls.objects.filter(
            organisation=issue.project.organisation,
            project=issue.project,
            severity=issue.severity,
            is_active=True
        ).first()
        
        if not rule:
            rule = cls.objects.filter(
                organisation=issue.project.organisation,
                project__isnull=True,
                severity=issue.severity,
                is_active=True
            ).first()

        return rule


# ---------------------------------------------------------------------------
# Outbound incident-analysis notifications — Items #22 + #23.
# ---------------------------------------------------------------------------


class IncidentNotificationChannel(models.Model):
    """
    Outbound destination for post-RCA notifications.

    Four kinds today:

    * ``slack``     — Incoming Webhook URL. Posts a Block Kit message.
    * ``teams``     — Incoming Webhook connector URL. Posts a MessageCard.
    * ``pagerduty`` — Events API v2 integration key. Sends a change event
                      linked to the alert-triggered incident.
    * ``opsgenie``  — API key + region. Adds a note to the matching alert.

    Called by ``notifications.incident_dispatcher.dispatch`` at two
    points in the batch pipeline:

    1. After every batch analysis completes (any batch, scheduled or
       alert-triggered).
    2. After alert-triggered analyses specifically (see
       ``Data.tasks.analyze_alert_ondemand``). PagerDuty + OpsGenie
       channels are usually filtered to alert-triggered only via
       ``trigger_events``.

    Filters:

    * ``trigger_events`` — subset of ``TRIGGER_CHOICES``. When empty,
      channel matches all events (fires on every analysis).
    * ``min_severity`` — severity threshold; only issues at or above
      fire (CRITICAL > HIGH > MEDIUM > LOW > INFO). Empty = any.

    Security:

    * ``webhook_url`` + ``api_key`` encrypted at rest via
      ``providers.encryption.encrypt_value``.
    * Send failures are logged + swallowed — a broken Slack workspace
      must not fail the batch analysis pipeline.
    * Per-channel rate limit at 60/min (upstream providers accept
      much more; the cap protects us from an errant filter causing
      floods).
    """

    KIND_CHOICES = [
        ('slack', 'Slack'),
        ('teams', 'Microsoft Teams'),
        ('pagerduty', 'PagerDuty'),
        ('opsgenie', 'OpsGenie'),
        # PR-N (2026-09-21): email joins the delivery-target set so the
        # settings surface matches the Grafana / Alertmanager pattern
        # (one uniform table of destinations). Email addresses live on
        # ``extra_config['to']`` (str or list[str]); optional overrides
        # ``extra_config['from']`` + ``extra_config['reply_to']`` fall
        # back to the site's DEFAULT_FROM_EMAIL when unset.
        ('email', 'Email'),
    ]

    # Where the dispatcher gets called from.
    TRIGGER_CHOICES = [
        ('batch_analyzed', 'Any batch analyzed'),
        ('alert_triggered', 'Alert-triggered batch analyzed'),
        ('critical_issue', 'Batch produced ≥1 critical issue'),
    ]

    SEVERITY_ORDER = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='incident_channels',
    )
    name = models.CharField(
        max_length=100,
        help_text='Human-readable label (e.g. "SRE Slack", "prod PagerDuty").',
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES)

    # For slack + teams: the incoming webhook URL.
    # Empty for pagerduty + opsgenie (those use api_key).
    webhook_url = models.CharField(max_length=500, blank=True, default='')

    # For pagerduty (integration key) + opsgenie (API key).
    # Empty for slack + teams.
    api_key = models.CharField(max_length=500, blank=True, default='')

    # Provider-specific extras — e.g. opsgenie region ('us' | 'eu'),
    # slack channel override, teams team id.
    extra_config = models.JSONField(default=dict, blank=True)

    # When to fire. Empty list = every event.
    trigger_events = models.JSONField(default=list, blank=True)

    # Minimum severity to fire. Empty string = any.
    min_severity = models.CharField(max_length=16, blank=True, default='')

    is_active = models.BooleanField(default=True)

    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notifications_incident_channel'
        indexes = [
            models.Index(fields=['organisation', 'is_active'], name='inc_chan_org_active_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'

    # ------------------------------------------------------------------
    # Encryption — mirror ObservabilityIntegration pattern
    # ------------------------------------------------------------------

    def set_webhook_url(self, raw: str):
        from providers.encryption import encrypt_value
        self.webhook_url = encrypt_value(raw) if raw else ''

    def get_webhook_url(self) -> str:
        if not self.webhook_url:
            return ''
        try:
            from providers.encryption import decrypt_value
            return decrypt_value(self.webhook_url)
        except Exception:
            return ''

    def set_api_key(self, raw: str):
        from providers.encryption import encrypt_value
        self.api_key = encrypt_value(raw) if raw else ''

    def get_api_key(self) -> str:
        if not self.api_key:
            return ''
        try:
            from providers.encryption import decrypt_value
            return decrypt_value(self.api_key)
        except Exception:
            return ''

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def matches_event(self, event_name: str) -> bool:
        """True when the channel should fire for ``event_name``."""
        if not self.is_active:
            return False
        if not self.trigger_events:
            # Empty = match every event.
            return True
        return event_name in self.trigger_events

    def meets_severity(self, severity: str) -> bool:
        """True when the given issue severity is >= min_severity."""
        if not self.min_severity:
            return True
        try:
            floor = self.SEVERITY_ORDER.index(self.min_severity.upper())
            got = self.SEVERITY_ORDER.index((severity or '').upper())
            return got >= floor
        except ValueError:
            return True   # unknown severity → don't block


class NotificationRoutingRule(models.Model):
    """PR-N phase 2 (2026-09-26): the Alertmanager-style route table.

    Each rule declares a MATCHER (which incidents apply) and a set of
    TARGETS (which delivery channels get notified when a match fires).
    The dispatcher walks every ``is_active`` rule and picks the union
    of targets from matching rules — deterministic, flat, no tree
    semantics yet (Alertmanager's ``continue: true`` is implicit
    everywhere for now; a follow-up PR can add explicit branch
    control).

    Matcher fields are all AND-ed:
    * ``min_severity`` — same 5-level ordering as
      ``IncidentNotificationChannel.SEVERITY_ORDER``.
    * ``environments`` — list of env names the rule fires for.
      Empty list = every environment.
    * ``services`` — list of service names. Empty = every service.
    * ``event_types`` — one or more of ``batch_analyzed``,
      ``alert_triggered``, ``critical_issue``. Empty = every event.

    Backfill migration (see 0005): one catch-all rule per org is
    created targeting every existing active channel so behaviour
    on 2026-09-26 stays identical to the "all channels see every
    event" rule the dispatcher had before this PR. Operators then
    tighten each rule as needed.
    """

    organisation = models.ForeignKey(
        'Organisations.Organisations',
        on_delete=models.CASCADE,
        related_name='routing_rules',
    )
    name = models.CharField(
        max_length=100,
        help_text='Human-readable label (e.g. "SRE — prod criticals").',
    )
    is_active = models.BooleanField(default=True)

    # Matcher — all AND-ed. Empty list == "no filter on this axis".
    min_severity = models.CharField(
        max_length=16, blank=True, default='',
        help_text='CRITICAL / HIGH / MEDIUM / LOW. Empty = any severity.',
    )
    environments = models.JSONField(default=list, blank=True)
    services = models.JSONField(default=list, blank=True)
    event_types = models.JSONField(default=list, blank=True)

    # Targets — which channels fire when this rule matches.
    targets = models.ManyToManyField(
        IncidentNotificationChannel, related_name='routing_rules',
    )

    # Ops behaviour flags. Left as fields so a follow-up UI can wire
    # them without another migration.
    suppress_for_minutes = models.PositiveIntegerField(default=0)
    escalate_after_minutes = models.PositiveIntegerField(default=0)
    priority = models.PositiveIntegerField(
        default=100,
        help_text='Lower value → evaluated earlier (informational; '
                  'union semantics today).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'notifications_routing_rule'
        indexes = [
            models.Index(fields=['organisation', 'is_active'],
                         name='routing_rule_org_active_idx'),
        ]
        ordering = ['priority', 'name']

    def __str__(self):
        return f'{self.name} (org={self.organisation_id})'

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def matches(self, *, event: str, severity: str,
                environment: str, service: str) -> bool:
        if not self.is_active:
            return False
        if self.event_types and event not in self.event_types:
            return False
        if self.environments and environment and environment not in self.environments:
            return False
        if self.services and service and service not in self.services:
            return False
        if self.min_severity:
            try:
                floor = IncidentNotificationChannel.SEVERITY_ORDER.index(
                    self.min_severity.upper(),
                )
                got = IncidentNotificationChannel.SEVERITY_ORDER.index(
                    (severity or '').upper(),
                )
                if got < floor:
                    return False
            except ValueError:
                pass  # unknown severity → don't block
        return True