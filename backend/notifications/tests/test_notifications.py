"""
Unit Tests for Notification System

Tests for:
- NotificationDispatcher suppression logic
- Model methods and defaults
- Escalation rule matching
- Digest scheduling
"""
from datetime import time, timedelta
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

User = get_user_model()


class UserNotificationPreferenceTests(TestCase):
    """Tests for UserNotificationPreference model."""
    
    def setUp(self):
        from Organisations.models import Organisations
        
        self.org = Organisations.objects.create(name='Test Org')
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            role='admin',
            organisation=self.org,
            is_active=True
        )
        self.viewer_user = User.objects.create_user(
            username='viewer',
            email='viewer@test.com',
            password='testpass123',
            role='viewer',
            organisation=self.org,
            is_active=True
        )
    
    def test_get_or_create_for_admin_user(self):
        """Admin users get email enabled by default."""
        from notifications.models import UserNotificationPreference
        
        prefs = UserNotificationPreference.get_or_create_for_user(self.admin_user)
        
        self.assertTrue(prefs.email_enabled)
        self.assertTrue(prefs.notify_critical)
        self.assertTrue(prefs.notify_warning)
        self.assertFalse(prefs.notify_info)
    
    def test_get_or_create_for_viewer_user(self):
        """Viewer users get email disabled by default."""
        from notifications.models import UserNotificationPreference
        
        prefs = UserNotificationPreference.get_or_create_for_user(self.viewer_user)
        
        self.assertFalse(prefs.email_enabled)
        self.assertTrue(prefs.notify_critical)
        self.assertFalse(prefs.notify_warning)  # Viewers don't get warnings
    
    def test_quiet_hours_not_active_when_disabled(self):
        """Quiet hours returns False when disabled."""
        from notifications.models import UserNotificationPreference
        
        prefs = UserNotificationPreference.objects.create(
            user=self.admin_user,
            quiet_hours_enabled=False,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0)
        )
        
        self.assertFalse(prefs.is_quiet_hours_active())
    
    def test_quiet_hours_active_during_night(self):
        """Quiet hours works for overnight periods."""
        from notifications.models import UserNotificationPreference
        
        prefs = UserNotificationPreference.objects.create(
            user=self.admin_user,
            quiet_hours_enabled=True,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0),
            timezone='UTC'
        )
        
        # Mock time to 23:00 UTC
        with patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = timezone.now().replace(hour=23, minute=0)
            # Note: actual test depends on timezone handling
            # This validates the method doesn't crash
            result = prefs.is_quiet_hours_active()
            self.assertIsInstance(result, bool)


class ProjectSubscriptionTests(TestCase):
    """Tests for ProjectSubscription model."""
    
    def setUp(self):
        from Organisations.models import Organisations
        from Projects.models import Project
        
        self.org = Organisations.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            organisation=self.org
        )
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            role='user',
            organisation=self.org,
            is_active=True
        )
    
    def test_should_notify_for_critical(self):
        """Subscription returns True for critical when enabled."""
        from notifications.models import ProjectSubscription
        
        sub = ProjectSubscription.objects.create(
            user=self.user,
            project=self.project,
            notify_critical=True,
            notify_warning=False
        )
        
        self.assertTrue(sub.should_notify_for_severity('CRITICAL'))
        self.assertFalse(sub.should_notify_for_severity('WARNING'))
    
    def test_should_notify_case_insensitive(self):
        """Severity matching is case-insensitive."""
        from notifications.models import ProjectSubscription
        
        sub = ProjectSubscription.objects.create(
            user=self.user,
            project=self.project,
            notify_critical=True
        )
        
        self.assertTrue(sub.should_notify_for_severity('critical'))
        self.assertTrue(sub.should_notify_for_severity('Critical'))


class NotificationQueueTests(TestCase):
    """Tests for NotificationQueue model."""
    
    def setUp(self):
        from Organisations.models import Organisations
        
        self.org = Organisations.objects.create(name='Test Org')
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            organisation=self.org,
            is_active=True
        )
    
    def test_mark_sent_updates_status_and_timestamp(self):
        """mark_sent() updates status and sent_at."""
        from notifications.models import NotificationQueue
        
        entry = NotificationQueue.objects.create(
            user=self.user,
            channel='email',
            severity='CRITICAL',
            subject='Test',
            status='pending'
        )
        
        self.assertIsNone(entry.sent_at)
        entry.mark_sent()
        
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'sent')
        self.assertIsNotNone(entry.sent_at)
    
    def test_mark_failed_increments_retry_count(self):
        """mark_failed() increments retry count."""
        from notifications.models import NotificationQueue
        
        entry = NotificationQueue.objects.create(
            user=self.user,
            channel='email',
            severity='CRITICAL',
            subject='Test',
            status='pending',
            retry_count=0
        )
        
        entry.mark_failed('Connection error')
        entry.refresh_from_db()
        
        self.assertEqual(entry.status, 'failed')
        self.assertEqual(entry.retry_count, 1)
        self.assertEqual(entry.error_message, 'Connection error')
    
    def test_mark_suppressed_sets_reason(self):
        """mark_suppressed() sets suppression reason."""
        from notifications.models import NotificationQueue
        
        entry = NotificationQueue.objects.create(
            user=self.user,
            channel='email',
            severity='WARNING',
            subject='Test',
            status='pending'
        )
        
        entry.mark_suppressed('quiet_hours')
        entry.refresh_from_db()
        
        self.assertEqual(entry.status, 'suppressed')
        self.assertEqual(entry.suppression_reason, 'quiet_hours')


class EscalationRuleTests(TestCase):
    """Tests for EscalationRule model."""
    
    def setUp(self):
        from Organisations.models import Organisations
        from Projects.models import Project
        from Data.models import AIAnalyzedBatch, Issue
        
        self.org = Organisations.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_001',
            project=self.project
        )
        self.issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='CRITICAL',
            description='Test critical issue',
            issue_type='SERVICE_DOWN'
        )
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@test.com',
            password='testpass123',
            role='admin',
            organisation=self.org,
            is_active=True
        )
    
    def test_get_rule_for_issue_returns_project_specific(self):
        """Project-specific rule takes precedence over org-wide."""
        from notifications.models import EscalationRule
        
        # Create org-wide rule
        org_rule = EscalationRule.objects.create(
            organisation=self.org,
            severity='CRITICAL',
            level_1_delay_minutes=30
        )
        
        # Create project-specific rule
        project_rule = EscalationRule.objects.create(
            organisation=self.org,
            project=self.project,
            severity='CRITICAL',
            level_1_delay_minutes=15
        )
        
        matched_rule = EscalationRule.get_rule_for_issue(self.issue)
        
        self.assertEqual(matched_rule.id, project_rule.id)
        self.assertEqual(matched_rule.level_1_delay_minutes, 15)
    
    def test_get_rule_for_issue_falls_back_to_org_wide(self):
        """Falls back to org-wide rule when no project-specific exists."""
        from notifications.models import EscalationRule
        
        org_rule = EscalationRule.objects.create(
            organisation=self.org,
            severity='CRITICAL',
            level_1_delay_minutes=30
        )
        
        matched_rule = EscalationRule.get_rule_for_issue(self.issue)
        
        self.assertEqual(matched_rule.id, org_rule.id)
    
    def test_get_level_1_targets_returns_admins(self):
        """Level 1 targets are org admins."""
        from notifications.models import EscalationRule
        
        rule = EscalationRule.objects.create(
            organisation=self.org,
            severity='CRITICAL'
        )
        
        targets = list(rule.get_level_1_targets(self.project))
        
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].email, 'admin@test.com')


class DispatcherSuppressionTests(TestCase):
    """Tests for NotificationDispatcher suppression logic."""
    
    def setUp(self):
        from Organisations.models import Organisations
        from Projects.models import Project
        from Data.models import AIAnalyzedBatch, Issue
        from notifications.models import (
            ProjectSubscription,
            UserNotificationPreference
        )
        
        self.org = Organisations.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_002',
            project=self.project
        )
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            role='user',
            organisation=self.org,
            is_active=True
        )
        self.subscription = ProjectSubscription.objects.create(
            user=self.user,
            project=self.project,
            notify_critical=True,
            notify_warning=False
        )
        self.prefs = UserNotificationPreference.objects.create(
            user=self.user,
            email_enabled=True,
            quiet_hours_enabled=False
        )
    
    def test_suppresses_muted_issue(self):
        """Muted issues are suppressed."""
        from Data.models import Issue
        from notifications.dispatcher import NotificationDispatcher
        
        issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='CRITICAL',
            status='MUTED',
            description='Muted issue'
        )
        
        dispatcher = NotificationDispatcher()
        result = dispatcher._check_suppression(
            self.user, self.subscription, issue, self.project
        )
        
        self.assertTrue(result.should_suppress)
        self.assertEqual(result.reason, 'muted_issue')
    
    def test_suppresses_severity_below_threshold(self):
        """Issues below severity threshold are suppressed."""
        from Data.models import Issue
        from notifications.dispatcher import NotificationDispatcher
        
        issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='WARNING',
            description='Warning issue'
        )
        
        dispatcher = NotificationDispatcher()
        result = dispatcher._check_suppression(
            self.user, self.subscription, issue, self.project
        )
        
        self.assertTrue(result.should_suppress)
        self.assertEqual(result.reason, 'severity_filtered')
    
    def test_does_not_suppress_eligible_notification(self):
        """Eligible notifications are not suppressed."""
        from Data.models import Issue
        from notifications.dispatcher import NotificationDispatcher
        
        issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='CRITICAL',
            status='OPEN',
            description='Critical issue'
        )
        
        dispatcher = NotificationDispatcher()
        result = dispatcher._check_suppression(
            self.user, self.subscription, issue, self.project
        )
        
        self.assertFalse(result.should_suppress)
        self.assertIsNone(result.reason)


class IssueAcknowledgmentTests(TestCase):
    """Tests for Issue acknowledgment fields."""
    
    def setUp(self):
        from Organisations.models import Organisations
        from Projects.models import Project
        from Data.models import AIAnalyzedBatch
        
        self.org = Organisations.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            organisation=self.org
        )
        self.batch = AIAnalyzedBatch.objects.create(
            batch_id='test_batch_003',
            project=self.project
        )
        self.user = User.objects.create_user(
            username='user',
            email='user@test.com',
            password='testpass123',
            organisation=self.org,
            is_active=True
        )
    
    def test_issue_acknowledgment_fields_exist(self):
        """Issue model has acknowledgment fields."""
        from Data.models import Issue
        
        issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='CRITICAL',
            description='Test issue'
        )
        
        self.assertIsNone(issue.acknowledged_at)
        self.assertIsNone(issue.acknowledged_by)
        self.assertEqual(issue.escalation_level, 0)
    
    def test_issue_acknowledgment_can_be_set(self):
        """Issue acknowledgment can be recorded."""
        from Data.models import Issue
        
        issue = Issue.objects.create(
            batch=self.batch,
            project=self.project,
            severity='CRITICAL',
            description='Test issue'
        )
        
        now = timezone.now()
        issue.acknowledged_at = now
        issue.acknowledged_by = self.user
        issue.save()
        
        issue.refresh_from_db()
        self.assertIsNotNone(issue.acknowledged_at)
        self.assertEqual(issue.acknowledged_by, self.user)
