"""
Notification Dispatcher Service

Central notification decision logic for the multi-tenant email system.
Handles:
- Suppression checks (muting, quiet hours, subscriptions)
- Channel routing (email, Slack, Teams, in-app)
- Digest queueing
- Escalation triggering
"""
import logging
from datetime import timedelta
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
        from org_settings.models import NotificationSettings
        
        project = issue.project
        if not project:
            logger.warning(f"Issue {issue.id} has no project, skipping notifications")
            return []
        
        # Get org settings
        org_settings = self._get_org_settings(project.organisation)
        
        # Check org-level severity filter
        if issue.severity == 'CRITICAL' and not org_settings.notify_on_critical:
            logger.debug(f"Org {project.organisation.name} has critical notifications disabled")
            return []
        if issue.severity == 'WARNING' and not org_settings.notify_on_warning:
            logger.debug(f"Org {project.organisation.name} has warning notifications disabled")
            return []
        
        # Get project subscribers (explicit opt-in)
        subscriptions = ProjectSubscription.objects.filter(
            project=project
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
        
        # Handle webhook notifications (org-level, not per-user)
        self._send_webhooks(issue, batch, project, org_settings)
        
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
        
        # 2. Check severity threshold on subscription
        if not subscription.should_notify_for_severity(issue.severity):
            return SuppressionResult(True, 'severity_filtered')
        
        # 3. Check quiet hours
        prefs = getattr(user, 'notification_preferences', None)
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
    
    def _get_org_settings(self, organisation):
        """Get or create org notification settings."""
        from org_settings.models import NotificationSettings
        
        settings_obj, _ = NotificationSettings.objects.get_or_create(
            organisation=organisation,
            defaults={
                'email_enabled': True,
                'notify_on_critical': True,
                'notify_on_warning': False,
            }
        )
        return settings_obj
    
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
                template_name='critical_issues_notification.html',
                organisation=project.organisation
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
        from org_settings.models import NotificationSettings
        
        # Calculate next digest time based on org settings and frequency
        org_settings = self._get_org_settings(project.organisation)
        scheduled_for = self._calculate_digest_time(prefs.digest_frequency, org_settings)
        
        NotificationQueue.objects.create(
            user=user,
            issue=issue,
            batch=batch,
            project=project,
            channel='email',
            severity=issue.severity,
            subject=f"Digest: {issue.issue_type}",
            status='queued_for_digest',
            scheduled_for=scheduled_for
        )
    
    def _calculate_digest_time(self, frequency, org_settings):
        """Calculate next digest delivery time."""
        now = timezone.now()
        
        if frequency == 'hourly':
            # Next hour
            return now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        elif frequency == 'daily':
            # Org's configured daily time
            hour, minute = map(int, org_settings.daily_digest_time.split(':'))
            next_digest = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_digest <= now:
                next_digest += timedelta(days=1)
            return next_digest
        elif frequency == 'weekly':
            # Next Monday at org's daily time
            hour, minute = map(int, org_settings.daily_digest_time.split(':'))
            days_until_monday = (7 - now.weekday()) % 7 or 7
            next_monday = now + timedelta(days=days_until_monday)
            return next_monday.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            return None  # immediate
    
    def _send_webhooks(self, issue, batch, project, org_settings):
        """Send Slack/Teams webhook notifications."""
        from org_settings.webhooks import (
            send_slack_webhook, format_slack_alert,
            send_teams_webhook, format_teams_alert
        )
        
        if not batch:
            return
        
        base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')
        dashboard_url = f"{base_url}/dash/data/{batch.batch_id}"
        severity = issue.severity.lower()
        
        if org_settings.slack_enabled and org_settings.slack_webhook_url:
            try:
                slack_message = format_slack_alert(
                    batch_id=batch.batch_id,
                    issues_count=1,
                    severity=severity,
                    dashboard_url=dashboard_url
                )
                success, error = send_slack_webhook(org_settings.slack_webhook_url, slack_message)
                if not success:
                    logger.error(f"Slack webhook failed: {error}")
            except Exception as e:
                logger.error(f"Slack webhook error: {e}")
        
        if org_settings.teams_enabled and org_settings.teams_webhook_url:
            try:
                teams_message = format_teams_alert(
                    batch_id=batch.batch_id,
                    issues_count=1,
                    severity=severity,
                    dashboard_url=dashboard_url
                )
                success, error = send_teams_webhook(org_settings.teams_webhook_url, teams_message)
                if not success:
                    logger.error(f"Teams webhook failed: {error}")
            except Exception as e:
                logger.error(f"Teams webhook error: {e}")


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
