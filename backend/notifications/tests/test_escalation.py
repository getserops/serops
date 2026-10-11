from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from notifications.models import NotificationQueue, EscalationRule, Notification
from Data.models import Issue, AIAnalyzedBatch
from Projects.models import Project
from Organisations.models import Organisations
from notifications.tasks import check_escalations

User = get_user_model()

class EscalationLogicTest(TestCase):
    def setUp(self):
        # Create Org and Users
        self.org = Organisations.objects.create(name="Test Org")
        # is_active=True is required — get_level_1_targets filters out
        # inactive users, so an inactive admin would silently drop the
        # escalation notification (was the historical failure of this
        # test after the User model default flipped to is_active=False).
        self.admin = User.objects.create_user(
            email="admin@test.com", username="admin",
            role='admin', organisation=self.org, is_active=True,
        )
        self.user = User.objects.create_user(
            email="user@test.com", username="user",
            role='user', organisation=self.org, is_active=True,
        )
        # PR-N phase 2 (2026-09-26): the ``NotificationSettings.escalation_enabled``
        # kill-switch was retired. Escalation is now controlled purely
        # by whether the org has any ``EscalationRule`` — the rule
        # created below is enough. No settings row needed.

        # Create Project
        self.project = Project.objects.create(
            name="Test Project", organisation=self.org
        )
        
        # Create Escalation Rule
        self.rule = EscalationRule.objects.create(
            organisation=self.org,
            project=self.project,
            severity='CRITICAL',
            level_1_delay_minutes=15,
            level_2_delay_minutes=30
        )
        
        # Create Issue (Critical, Unacknowledged)
        self.batch = AIAnalyzedBatch.objects.create(
            project=self.project,
            batch_id="batch-123"
        )
        self.issue = Issue.objects.create(
            project=self.project,
            batch=self.batch,
            severity='CRITICAL',
            status='OPEN',
            issue_type='Error',
            description='Something bad happened',
            created_at=timezone.now() - timedelta(minutes=20) # Old enough for L1
        )
        # Mock created_at (auto_now_add makes it hard to set directly, need to update after create)
        Issue.objects.filter(id=self.issue.id).update(
            created_at=timezone.now() - timedelta(minutes=20)
        )
        self.issue.refresh_from_db()

    def test_escalation_to_level_1(self):
        """Test that issue escalates to Level 1 after delay."""
        # Run task
        result = check_escalations()
        
        # Reload issue
        self.issue.refresh_from_db()
        
        # Check level
        self.assertEqual(self.issue.escalation_level, 1)
        
        # Check notification sent to project admin (admin)
        notifications = Notification.objects.filter(
            user=self.admin, notification_type='escalation'
        )
        self.assertTrue(notifications.exists())
        self.assertIn("Level 1", notifications.first().subject)

    def test_no_escalation_if_acknowledged(self):
        """Test that acknowledged issues do not escalate."""
        self.issue.acknowledged_at = timezone.now()
        self.issue.save()
        
        check_escalations()
        
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.escalation_level, 0)
