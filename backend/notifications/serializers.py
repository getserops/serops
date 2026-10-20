from rest_framework import serializers
from Utils.scoped_relations import limit_relations
from .models import (
    Notification,
    UserNotificationPreference,
    ProjectSubscription,
    NotificationQueue,
    EscalationRule,
)


class NotificationSerializer(serializers.ModelSerializer):
    """Serializer for in-app notifications."""
    
    class Meta:
        model = Notification
        fields = [
            'id', 'subject', 'message', 'is_read', 'created_at',
            'notification_type', 'batch_id', 'issue'
        ]
        # Members only mark notifications read; what they point at is set
        # by SerOps (an issue id of another organisation must not be settable).
        read_only_fields = ['id', 'created_at', 'subject', 'message', 'notification_type', 'batch_id', 'issue']


class NotificationCountSerializer(serializers.Serializer):
    """Serializer for unread count response."""
    unread_count = serializers.IntegerField()


class MarkAllReadResponseSerializer(serializers.Serializer):
    """Serializer for mark all read response."""
    status = serializers.CharField()
    message = serializers.CharField()


class UserNotificationPreferenceSerializer(serializers.ModelSerializer):
    """Serializer for user notification preferences."""
    
    class Meta:
        model = UserNotificationPreference
        fields = [
            'id', 'email_enabled', 'in_app_enabled',
            'notify_critical', 'notify_warning', 'notify_info',
            'digest_frequency', 'quiet_hours_enabled',
            'quiet_hours_start', 'quiet_hours_end', 'timezone',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProjectSubscriptionSerializer(serializers.ModelSerializer):
    """Serializer for project notification subscriptions."""
    # A subscription to another organisation's project would deliver its
    # incidents: only the member's own organisation's projects.
    def get_fields(self):
        from Projects.models import Project
        return limit_relations(super().get_fields(), self.context.get('request'),
                               project=lambda u, org: Project.objects.filter(organisation=org))

    
    project_name = serializers.CharField(source='project.name', read_only=True)
    
    class Meta:
        model = ProjectSubscription
        fields = [
            'id', 'project', 'project_name',
            'notify_critical', 'notify_warning', 'notify_info',
            'email_override', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class ProjectSubscriptionCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating project subscriptions."""
    # A subscription to another organisation's project would deliver its
    # incidents: only the member's own organisation's projects.
    def get_fields(self):
        from Projects.models import Project
        return limit_relations(super().get_fields(), self.context.get('request'),
                               project=lambda u, org: Project.objects.filter(organisation=org))

    
    class Meta:
        model = ProjectSubscription
        fields = [
            'project', 'notify_critical', 'notify_warning', 'notify_info',
            'email_override'
        ]
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class IssueAcknowledgeSerializer(serializers.Serializer):
    """Serializer for acknowledging an issue."""
    
    issue_id = serializers.IntegerField()
    
    def validate_issue_id(self, value):
        from Data.models import Issue

        # Org-scoped lookup — prior check `issue.project.organisation`
        # was silently skipped for issues with project=None, leaking
        # org-only issues across tenants. Issue.organisation is a direct
        # FK so the check is unambiguous.
        user = self.context['request'].user
        user_org = getattr(user, 'organisation', None)
        if not user_org:
            raise serializers.ValidationError("Issue not found")
        qs = Issue.objects.all()
        qs = qs.filter(organisation=user_org)
        if not qs.filter(id=value).exists():
            raise serializers.ValidationError("Issue not found")

        return value


class NotificationQueueSerializer(serializers.ModelSerializer):
    """Serializer for notification queue (admin view)."""
    
    user_email = serializers.CharField(source='user.email', read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True)
    
    class Meta:
        model = NotificationQueue
        fields = [
            'id', 'user_email', 'project_name', 'channel', 'severity',
            'subject', 'status', 'suppression_reason',
            'created_at', 'scheduled_for', 'sent_at', 'retry_count'
        ]
        read_only_fields = fields


class EscalationRuleSerializer(serializers.ModelSerializer):
    """Serializer for escalation rules."""
    def get_fields(self):
        from Projects.models import Project
        return limit_relations(super().get_fields(), self.context.get('request'),
                               project=lambda u, org: Project.objects.filter(organisation=org))

    
    project_name = serializers.CharField(source='project.name', read_only=True)
    
    class Meta:
        model = EscalationRule
        fields = [
            'id', 'project', 'project_name', 'severity',
            'level_1_delay_minutes', 'level_2_delay_minutes',
            'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate(self, data):
        """Ensure delays make sense (L2 > L1)."""
        l1 = data.get('level_1_delay_minutes', self.instance.level_1_delay_minutes if self.instance else 0)
        l2 = data.get('level_2_delay_minutes', self.instance.level_2_delay_minutes if self.instance else 0)
        
        if l2 <= l1:
            raise serializers.ValidationError({
                "level_2_delay_minutes": "Level 2 delay must be greater than Level 1 delay."
            })
        return data