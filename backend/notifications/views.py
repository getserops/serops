from Middlewares.rbac import Requires
from rest_framework.permissions import IsAuthenticated
from rest_framework import generics, permissions
from rest_framework.response import Response
from .models import Notification
from .serializers import NotificationSerializer, NotificationCountSerializer, MarkAllReadResponseSerializer
from django.contrib.auth import get_user_model
from django.db.models import Q
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi


User = get_user_model()

class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.all()
            
        queryset = Notification.objects.filter(user=self.request.user).order_by('-created_at')
        
        notification_type = self.request.query_params.get('type', None)
        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)
            
        is_read = self.request.query_params.get('is_read', None)
        if is_read is not None:
            queryset = queryset.filter(is_read=is_read.lower() == 'true')
            
        return queryset

class ReadNotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.all()
            
        return Notification.objects.filter(
            user=self.request.user,
            is_read=True
        ).order_by('-created_at')

class NotificationDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Notification.objects.all()
        return Notification.objects.filter(user=self.request.user)

class MarkAllAsReadView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    serializer_class = MarkAllReadResponseSerializer

    @swagger_auto_schema(
        operation_description="Mark all notifications as read",
        responses={200: MarkAllReadResponseSerializer}
    )
    def put(self, request, *args, **kwargs):
        if getattr(self, 'swagger_fake_view', False):
            return Response({
                'status': 'success',
                'message': 'Notifications marked as read'
            })
            
        updated = Notification.objects.filter(
            user=request.user, 
            is_read=False
        ).update(is_read=True)
        
        return Response({
            'status': 'success',
            'message': f'{updated} notifications marquées comme lues'
        })

class UnreadCountView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    serializer_class = NotificationCountSerializer

    @swagger_auto_schema(
        operation_description="Get count of unread notifications",
        responses={200: NotificationCountSerializer}
    )
    def get(self, request, *args, **kwargs):
        if getattr(self, 'swagger_fake_view', False):
            return Response({'unread_count': 0})
            
        count = Notification.objects.filter(
            user=request.user, 
            is_read=False
        ).count()
        
        return Response({'unread_count': count})
    




class DeleteNotificationView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)
        
    @swagger_auto_schema(
        operation_description="Delete a specific notification",
        responses={204: 'No content'}
    )
    def delete(self, request, *args, **kwargs):
        if getattr(self, 'swagger_fake_view', False):
            return Response(status=204)
            
        return super().delete(request, *args, **kwargs)

class DeleteAllNotificationsView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    
  
    @swagger_auto_schema(
    operation_description="Delete all notifications for current user",
    responses={
        200: openapi.Response(
            description="Notifications deleted",
            schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'status': openapi.Schema(type=openapi.TYPE_STRING),
                    'message': openapi.Schema(type=openapi.TYPE_STRING),
                    'deleted_count': openapi.Schema(type=openapi.TYPE_INTEGER),
                }
            )
        )
    }
)
    def delete(self, request, *args, **kwargs):
        if getattr(self, 'swagger_fake_view', False):
            return Response({
                'status': 'success',
                'message': 'Notifications deleted',
                'deleted_count': 0
            })
            
        deleted_count, _ = Notification.objects.filter(user=request.user).delete()
        
        return Response({
            'status': 'success',
            'message': 'Toutes les notifications ont été supprimées',
            'deleted_count': deleted_count
        })


# === NEW VIEWS FOR NOTIFICATION MANAGEMENT SYSTEM ===

from rest_framework import status
from django.utils import timezone
from .models import UserNotificationPreference, ProjectSubscription
from .serializers import (
    UserNotificationPreferenceSerializer,
    ProjectSubscriptionSerializer,
    ProjectSubscriptionCreateSerializer,
    IssueAcknowledgeSerializer,
)


class UserNotificationPreferenceView(generics.RetrieveUpdateAPIView):
    """
    GET/PUT the current user's notification preferences.
    Creates defaults on first access based on user role.
    """
    serializer_class = UserNotificationPreferenceSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    def get_object(self):
        return UserNotificationPreference.get_or_create_for_user(self.request.user)


class ProjectSubscriptionListView(generics.ListCreateAPIView):
    """
    GET: List all project subscriptions for current user.
    POST: Subscribe to a new project.
    """
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ProjectSubscriptionCreateSerializer
        return ProjectSubscriptionSerializer
    
    def get_queryset(self):
        return ProjectSubscription.objects.filter(
            user=self.request.user
        ).select_related('project')


class ProjectSubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PUT/DELETE a specific project subscription.
    """
    serializer_class = ProjectSubscriptionSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    def get_queryset(self):
        return ProjectSubscription.objects.filter(user=self.request.user)


class SubscribeToProjectView(generics.CreateAPIView):
    """
    Subscribe current user to a project by project ID.
    POST /projects/{project_id}/subscribe/
    """
    serializer_class = ProjectSubscriptionCreateSerializer
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    @swagger_auto_schema(
        operation_description="Subscribe to project notifications",
        responses={201: ProjectSubscriptionSerializer}
    )
    def post(self, request, project_id):
        from Projects.models import Project
        
        # Verify project exists and user has access
        try:
            project = Project.objects.get(
                id=project_id,
                organisation=request.user.organisation
            )
        except Project.DoesNotExist:
            return Response(
                {'error': 'Project not found or access denied'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if already subscribed
        existing = ProjectSubscription.objects.filter(
            user=request.user,
            project=project
        ).first()
        
        if existing:
            return Response(
                {'error': 'Already subscribed to this project'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create subscription
        subscription = ProjectSubscription.objects.create(
            user=request.user,
            project=project,
            notify_critical=request.data.get('notify_critical', True),
            notify_warning=request.data.get('notify_warning', True),
            notify_info=request.data.get('notify_info', False),
        )
        
        return Response(
            ProjectSubscriptionSerializer(subscription).data,
            status=status.HTTP_201_CREATED
        )


class UnsubscribeFromProjectView(generics.DestroyAPIView):
    """
    Unsubscribe current user from a project by project ID.
    DELETE /projects/{project_id}/subscribe/
    """
    permission_classes = [IsAuthenticated, Requires(default='self.manage')]
    
    @swagger_auto_schema(
        operation_description="Unsubscribe from project notifications",
        responses={204: 'Unsubscribed'}
    )
    def delete(self, request, project_id):
        deleted, _ = ProjectSubscription.objects.filter(
            user=request.user,
            project_id=project_id
        ).delete()
        
        if deleted:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response(
            {'error': 'Not subscribed to this project'},
            status=status.HTTP_404_NOT_FOUND
        )


class IssueAcknowledgeView(generics.GenericAPIView):
    """
    Acknowledge an issue to stop escalation.
    POST /issues/{issue_id}/acknowledge/
    """
    serializer_class = IssueAcknowledgeSerializer
    # Acknowledging updates the issue: users and admins only.
    permission_classes = [IsAuthenticated, Requires(POST='issue.update')]
    
    @swagger_auto_schema(
        operation_description="Acknowledge an issue",
        responses={
            200: openapi.Response(
                description="Issue acknowledged",
                schema=openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    properties={
                        'status': openapi.Schema(type=openapi.TYPE_STRING),
                        'acknowledged_at': openapi.Schema(type=openapi.TYPE_STRING),
                    }
                )
            )
        }
    )
    def post(self, request, issue_id):
        from Data.models import Issue

        # Org-scoped fetch. Prior code checked `issue.project.organisation`
        # after fetching — that skipped the check entirely for issues
        # with project=None (a real cross-org leak on org-only issues).
        # Issue has a direct .organisation FK so the check is unambiguous.
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Response(
                {'error': 'Issue not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        qs = Issue.objects.all()
        qs = qs.filter(organisation=user_org)
        issue = qs.filter(id=issue_id).first()
        if issue is None:
            return Response(
                {'error': 'Issue not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Acknowledge the issue
        if not issue.acknowledged_at:
            issue.acknowledged_at = timezone.now()
            issue.acknowledged_by = request.user
            issue.save(update_fields=['acknowledged_at', 'acknowledged_by'])
        
        return Response({
            'status': 'acknowledged',
            'acknowledged_at': issue.acknowledged_at.isoformat(),
            'acknowledged_by': request.user.email,
        })


class EscalationRuleListView(generics.ListCreateAPIView):
    """
    GET: List escalation rules for user's organization.
    POST: Create a new escalation rule.
    Admin only.
    """
    from .models import EscalationRule
    from .serializers import EscalationRuleSerializer

    serializer_class = EscalationRuleSerializer
    permission_classes = [IsAuthenticated, Requires(default='alerting.manage')]
    
    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(
            organisation=self.request.user.organisation
        )
    
    def perform_create(self, serializer):
        # Enforce organization ownership
        serializer.save(organisation=self.request.user.organisation)


class EscalationRuleDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PUT/DELETE specific escalation rule.
    Admin only.
    """
    from .models import EscalationRule
    from .serializers import EscalationRuleSerializer

    serializer_class = EscalationRuleSerializer
    permission_classes = [IsAuthenticated, Requires(default='alerting.manage')]
    
    def get_queryset(self):
        return self.serializer_class.Meta.model.objects.filter(
            organisation=self.request.user.organisation
        )