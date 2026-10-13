"""
Notification Celery Tasks

Periodic tasks for:
- Escalation checking (runs every 5 minutes)
- Digest delivery (runs hourly)
- Failed notification retry (runs every 15 minutes)
"""
import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings

logger = logging.getLogger(__name__)
User = get_user_model()


@shared_task
def check_escalations():
    """
    Check for unacknowledged critical issues and escalate as needed.
    Uses role hierarchy: user -> admin -> org admins.
    
    Run every 5 minutes via Celery Beat.
    """
    from Data.models import Issue
    from notifications.models import EscalationRule, Notification, NotificationQueue

    now = timezone.now()
    escalated_count = 0

    # Find open critical issues that haven't been acknowledged
    critical_issues = Issue.objects.filter(
        severity='CRITICAL',
        status='OPEN',
        acknowledged_at__isnull=True,
        project__isnull=False,
    ).select_related('project', 'project__organisation')

    # PR-N phase 2 (2026-09-26): the ``NotificationSettings.escalation_enabled``
    # kill-switch is retired. Escalation is now controlled by whether
    # the org has any ``EscalationRule`` — no rule = no escalation, same
    # net effect as the old ``escalation_enabled=False`` toggle.

    for issue in critical_issues:
        rule = EscalationRule.get_rule_for_issue(issue)
        if not rule:
            continue
        
        issue_age_minutes = (now - issue.created_at).total_seconds() / 60
        
        # Determine if escalation is needed
        new_level = None
        if issue.escalation_level == 0 and issue_age_minutes >= rule.level_1_delay_minutes:
            new_level = 1
        elif issue.escalation_level == 1 and issue_age_minutes >= rule.level_2_delay_minutes:
            new_level = 2
        
        if new_level:
            issue.escalation_level = new_level
            issue.save(update_fields=['escalation_level'])
            
            # Get escalation targets based on role hierarchy
            if new_level == 1:
                targets = rule.get_level_1_targets(issue.project)
            else:
                targets = rule.get_level_2_targets(issue.project)
            
            # Send escalation notifications
            for user in targets:
                _send_escalation_notification(user, issue, new_level)
            
            escalated_count += 1
            logger.info(f"Escalated issue {issue.id} to level {new_level}")
    
    return f"Checked escalations: {escalated_count} issues escalated"


def _send_escalation_notification(user, issue, level):
    """Send escalation notification to a user."""
    from notifications.models import Notification, NotificationQueue
    from notifications.services import send_notification_email
    
    level_text = f"Level {level}"
    subject = f"ESCALATION ({level_text}): {issue.issue_type} in {issue.project.name}"
    
    # Create in-app notification
    Notification.objects.create(
        user=user,
        subject=subject,
        message=f"Issue unacknowledged for {issue.escalation_level * 15}+ minutes. {issue.description[:300]}",
        notification_type='escalation',
        issue=issue,
        batch_id=issue.batch.batch_id if issue.batch else None
    )
    
    # Queue email notification
    queue_entry = NotificationQueue.objects.create(
        user=user,
        issue=issue,
        batch=issue.batch,
        project=issue.project,
        channel='email',
        severity='CRITICAL',
        subject=subject,
        status='pending'
    )
    
    try:
        base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')
        batch_id = issue.batch.batch_id if issue.batch else 'N/A'
        dashboard_url = f"{base_url}/dash/data/{batch_id}"
        
        context = {
            'user': user,
            'batch_id': batch_id,
            'created_at': issue.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            'severity': 'CRITICAL',
            'issue_type': issue.issue_type,
            'project_name': issue.project.name,
            'description': issue.description[:500],
            'base_url': base_url,
            'dashboard_url': dashboard_url,
            'escalation_level': level,
            'is_escalation': True,
        }
        
        success = send_notification_email(
            user_email=user.email,
            subject=subject,
            context=context,
            template_name='critical_issues_notification.html',
            organisation=issue.project.organisation
        )
        
        if success:
            queue_entry.mark_sent()
        else:
            queue_entry.mark_failed('Email send failed')
            
    except Exception as e:
        queue_entry.mark_failed(str(e))
        logger.error(f"Escalation email failed for {user.email}: {e}")


@shared_task
def process_digest_notifications():
    """
    Send digest notifications to users who have queued notifications.
    
    Run hourly via Celery Beat.
    """
    from notifications.models import NotificationQueue, Notification
    from notifications.services import send_notification_email
    
    now = timezone.now()
    
    # Get queued notifications that are due
    pending = NotificationQueue.objects.filter(
        status='queued_for_digest',
        scheduled_for__lte=now
    ).select_related('user', 'issue', 'project').order_by('user', '-created_at')
    
    # Group by user
    user_notifications = {}
    for entry in pending:
        if entry.user_id not in user_notifications:
            user_notifications[entry.user_id] = {
                'user': entry.user,
                'entries': []
            }
        user_notifications[entry.user_id]['entries'].append(entry)
    
    sent_count = 0
    
    for user_id, data in user_notifications.items():
        user = data['user']
        entries = data['entries']
        
        # Build digest content
        critical_count = sum(1 for e in entries if e.severity == 'CRITICAL')
        warning_count = sum(1 for e in entries if e.severity == 'WARNING')
        
        subject = f"SerOps Digest: {critical_count} critical, {warning_count} warning issues"
        
        # Create summary message
        projects = set(e.project.name for e in entries if e.project)
        message = f"You have {len(entries)} pending notifications:\n"
        message += f"- Critical: {critical_count}\n"
        message += f"- Warning: {warning_count}\n"
        message += f"Projects: {', '.join(projects)}"
        
        # Create in-app digest notification
        Notification.objects.create(
            user=user,
            subject=subject,
            message=message,
            notification_type='digest'
        )
        
        # Send digest email
        try:
            base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')
            
            context = {
                'user': user,
                'entries': entries[:20],  # Limit to 20 in digest
                'critical_count': critical_count,
                'warning_count': warning_count,
                'total_count': len(entries),
                'projects': list(projects),
                'base_url': base_url,
                'is_digest': True,
            }
            
            # Resolve organisation from first entry's project
            org = None
            for e in entries:
                if e.project and hasattr(e.project, 'organisation'):
                    org = e.project.organisation
                    break

            # Use a digest-specific template if available
            send_notification_email(
                user_email=user.email,
                subject=subject,
                context=context,
                template_name='notification_digest.html',
                organisation=org
            )
            
            # Mark all as sent
            for entry in entries:
                entry.mark_sent()
            
            sent_count += 1
            
        except Exception as e:
            logger.error(f"Digest email failed for {user.email}: {e}")
            for entry in entries:
                entry.mark_failed(str(e))
    
    return f"Processed digests for {sent_count} users"


@shared_task
def retry_failed_notifications():
    """
    Retry failed notifications that haven't exceeded max retries.
    
    Run every 15 minutes via Celery Beat.
    """
    from notifications.models import NotificationQueue
    from notifications.services import send_notification_email
    
    MAX_RETRIES = 3
    
    # Get failed notifications eligible for retry
    failed = NotificationQueue.objects.filter(
        status='failed',
        retry_count__lt=MAX_RETRIES,
        channel='email'
    ).select_related('user', 'issue', 'project')[:50]  # Process in batches
    
    retried_count = 0
    
    for entry in failed:
        try:
            base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')
            batch_id = entry.batch.batch_id if entry.batch else 'N/A'
            dashboard_url = f"{base_url}/dash/data/{batch_id}"
            
            context = {
                'user': entry.user,
                'batch_id': batch_id,
                'severity': entry.severity,
                'project_name': entry.project.name if entry.project else 'N/A',
                'base_url': base_url,
                'dashboard_url': dashboard_url,
            }
            
            org = entry.project.organisation if entry.project else None
            success = send_notification_email(
                user_email=entry.user.email,
                subject=entry.subject,
                context=context,
                template_name='critical_issues_notification.html',
                organisation=org
            )
            
            if success:
                entry.mark_sent()
                retried_count += 1
            else:
                entry.mark_failed('Retry failed')
                
        except Exception as e:
            entry.mark_failed(str(e))
            logger.error(f"Retry failed for notification {entry.id}: {e}")
    
    return f"Retried {retried_count} failed notifications"


@shared_task
def cleanup_old_notifications():
    """
    Clean up old notification queue entries.
    
    Run daily via Celery Beat.
    """
    from notifications.models import NotificationQueue, Notification
    
    # Delete sent/suppressed queue entries older than 30 days
    cutoff = timezone.now() - timedelta(days=30)
    
    deleted_queue, _ = NotificationQueue.objects.filter(
        status__in=['sent', 'suppressed'],
        created_at__lt=cutoff
    ).delete()
    
    # Delete read in-app notifications older than 90 days
    deleted_notifications, _ = Notification.objects.filter(
        is_read=True,
        created_at__lt=timezone.now() - timedelta(days=90)
    ).delete()
    
    return f"Cleaned up {deleted_queue} queue entries, {deleted_notifications} notifications"
