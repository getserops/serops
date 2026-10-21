"""
Personal notifications for project subscribers.

A user who subscribes to a project (Profile → Notification preferences) gets
its issues by email and in the app, filtered by their own severity choices,
quiet hours and digest frequency. Team-wide delivery (Slack, Teams, PagerDuty,
Opsgenie, shared mailboxes) is the job of Delivery Channels and Routing Rules
in ``notifications.incident_dispatcher``; this module never sends to them.
"""
import logging
from datetime import timedelta
from zoneinfo import ZoneInfo
from django.utils import timezone
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)
User = get_user_model()


class SuppressionResult:
    """Result of a suppression check."""
    
    def __init__(self, should_suppress: bool, reason: str = None):
        self.should_suppress = should_suppress
        self.reason = reason
    
    def __bool__(self):
        return not self.should_suppress


class NotificationDispatcher:
    """
    Central dispatcher for all notification decisions.
    
    Usage:
        dispatcher = NotificationDispatcher()
        dispatcher.dispatch_issue_notification(issue, batch)
    """
    
    DUPLICATE_WINDOW_HOURS = 1  # Suppress duplicate notifications within this window
    
    def __init__(self):
        self._cache = {}
    
    def dispatch_issue_notification(self, issue, batch=None):
        """
        Dispatch notifications for an issue to all eligible subscribers.
        
        Args:
            issue: Issue instance
            batch: Optional AIAnalyzedBatch instance
        """
        from notifications.models import (
            ProjectSubscription,
            UserNotificationPreference,
            NotificationQueue,
            Notification,
        )
        project = issue.project
        if not project:
            logger.warning(f"Issue {issue.id} has no project, skipping notifications")
            return []

        # Explicit opt-in, and only people who still belong to the project's
        # organisation: a deactivated or departed user keeps no feed.
        subscriptions = ProjectSubscription.objects.filter(
            project=project,
            user__is_active=True,
            user__organisation_id=project.organisation_id,
        ).select_related('user', 'user__notification_preferences')
        
        notifications_sent = []
        
        for subscription in subscriptions:
            user = subscription.user
            
            # Run suppression checks
            suppression = self._check_suppression(user, subscription, issue, project)
            
            if suppression.should_suppress:
                # Record suppressed notification for audit
                NotificationQueue.objects.create(
                    user=user,
                    issue=issue,
                    batch=batch,
                    project=project,
                    channel='email',
                    severity=issue.severity,
                    subject=f"Suppressed: {issue.issue_type}",
                    status='suppressed',
                    suppression_reason=suppression.reason
                )
                continue
            
            # Get user preferences
            prefs = UserNotificationPreference.get_or_create_for_user(user)
            
            # Check digest mode
            if prefs.digest_frequency != 'immediate':
                self._queue_for_digest(user, issue, batch, project, prefs)
                notifications_sent.append({
                    'user': user.email,
                    'channel': 'digest',
                    'status': 'queued'
                })
                continue
            
            # Dispatch to enabled channels
            if prefs.email_enabled or subscription.email_override is True:
                if subscription.email_override is not False:
                    result = self._send_email(user, issue, batch, project)
                    notifications_sent.append(result)
            
            if prefs.in_app_enabled:
                result = self._create_in_app_notification(user, issue, batch)
                notifications_sent.append(result)

        logger.info(f"Dispatched {len(notifications_sent)} notifications for issue {issue.id}")
        return notifications_sent
    
    def _check_suppression(self, user, subscription, issue, project):
        """
        Check if notification should be suppressed.
        Returns SuppressionResult.
        """
        from notifications.models import NotificationQueue
        
        # 1. Check issue is muted
        if issue.status == 'MUTED':
            return SuppressionResult(True, 'muted_issue')
        
        if issue.muted_until and issue.muted_until > timezone.now():
            return SuppressionResult(True, 'muted_issue')
        
        # 2. Severity: the user's own choice (Profile) and the subscription's
        prefs = getattr(user, 'notification_preferences', None)
        if not subscription.should_notify_for_severity(issue.severity):
            return SuppressionResult(True, 'severity_filtered')
        if prefs and not {
            'CRITICAL': prefs.notify_critical,
            'WARNING': prefs.notify_warning,
            'INFO': prefs.notify_info,
        }.get((issue.severity or '').upper(), False):
            return SuppressionResult(True, 'severity_filtered')

        # 3. Check quiet hours
        if prefs and prefs.is_quiet_hours_active():
            return SuppressionResult(True, 'quiet_hours')
        
        # 4. Check duplicate notification
        recent = NotificationQueue.objects.filter(
            user=user,
            issue=issue,
            status='sent',
            sent_at__gte=timezone.now() - timedelta(hours=self.DUPLICATE_WINDOW_HOURS)
        ).exists()
        
        if recent:
            return SuppressionResult(True, 'duplicate')
        
        return SuppressionResult(False)
    
    def _send_email(self, user, issue, batch, project):
        """Send email notification for an issue."""
        from notifications.models import NotificationQueue
        from notifications.services import send_notification_email
        
        batch_id = batch.batch_id if batch else 'N/A'
        subject = f"{issue.severity}: {issue.issue_type} in {project.name}"
        
        queue_entry = NotificationQueue.objects.create(
            user=user,
            issue=issue,
            batch=batch,
            project=project,
            channel='email',
            severity=issue.severity,
            subject=subject,
            status='pending'
        )
        
        try:
            base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')
            dashboard_url = f"{base_url}/dash/data/{batch_id}"
            
            context = {
                'user': user,
                'batch_id': batch_id,
                'created_at': timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
                'severity': issue.severity,
                'issue_type': issue.issue_type,
                'project_name': project.name,
                'description': issue.description[:500],
                'base_url': base_url,
                'dashboard_url': dashboard_url,
            }
            
            success = send_notification_email(
                user_email=user.email,
                subject=subject,
                context=context,
                template_name='critical_issues_notification.html'
            )
            
            if success:
                queue_entry.mark_sent()
                return {'user': user.email, 'channel': 'email', 'status': 'sent'}
            else:
                queue_entry.mark_failed('Email send failed')
                return {'user': user.email, 'channel': 'email', 'status': 'failed'}
                
        except Exception as e:
            queue_entry.mark_failed(str(e))
            logger.error(f"Email notification failed for {user.email}: {e}")
            return {'user': user.email, 'channel': 'email', 'status': 'failed', 'error': str(e)}
    
    def _create_in_app_notification(self, user, issue, batch):
        """Create in-app notification record."""
        from notifications.models import Notification
        
        batch_id = batch.batch_id if batch else None
        notification_type = 'critical_issue' if issue.severity == 'CRITICAL' else 'warning_issue'
        
        Notification.objects.create(
            user=user,
            subject=f"{issue.severity}: {issue.issue_type}",
            message=issue.description[:500],
            notification_type=notification_type,
            batch_id=batch_id,
            issue=issue
        )
        
        return {'user': user.email, 'channel': 'in_app', 'status': 'created'}
    
    def _queue_for_digest(self, user, issue, batch, project, prefs):
        """Queue notification for digest delivery."""
        from notifications.models import NotificationQueue

        NotificationQueue.objects.create(
            user=user,
            issue=issue,
            batch=batch,
            project=project,
            channel='email',
            severity=issue.severity,
            subject=f"Digest: {issue.issue_type}",
            status='queued_for_digest',
            scheduled_for=self._calculate_digest_time(prefs.digest_frequency, prefs.timezone)
        )

    DIGEST_HOUR = 9  # daily and weekly digests arrive at 09:00 in the user's time zone

    def _calculate_digest_time(self, frequency, tz_name='UTC', now=None):
        """Next digest delivery time, or None for immediate delivery."""
        now = now or timezone.now()

        if frequency == 'hourly':
            return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        if frequency not in ('daily', 'weekly'):
            return None

        try:
            tz = ZoneInfo(tz_name or 'UTC')
        except (KeyError, ValueError):
            tz = ZoneInfo('UTC')
        local = now.astimezone(tz)
        nxt = local.replace(hour=self.DIGEST_HOUR, minute=0, second=0, microsecond=0)
        if frequency == 'daily':
            if nxt <= local:
                nxt += timedelta(days=1)
        else:
            nxt += timedelta(days=(7 - local.weekday()) % 7)
            if nxt <= local:
                nxt += timedelta(days=7)
        return nxt


def dispatch_for_batch_issues(batch, issues):
    """
    Convenience function to dispatch notifications for all issues in a batch.
    Groups issues by severity to avoid notification spam.
    """
    dispatcher = NotificationDispatcher()
    
    critical_issues = [i for i in issues if i.severity == 'CRITICAL']
    warning_issues = [i for i in issues if i.severity == 'WARNING']
    
    results = []
    
    # Dispatch critical issues individually
    for issue in critical_issues:
        results.extend(dispatcher.dispatch_issue_notification(issue, batch))
    
    # For warnings, could batch them (future enhancement)
    for issue in warning_issues:
        results.extend(dispatcher.dispatch_issue_notification(issue, batch))
    
    return results
