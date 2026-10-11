from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    NotificationListView,
    NotificationDetailView,
    MarkAllAsReadView,
    UnreadCountView,
    ReadNotificationListView,
    DeleteNotificationView,
    DeleteAllNotificationsView,
    # New views for notification management
    UserNotificationPreferenceView,
    ProjectSubscriptionListView,
    ProjectSubscriptionDetailView,
    ProjectSubscriptionDetailView,
    IssueAcknowledgeView,
    EscalationRuleListView,
    EscalationRuleDetailView,
)
from .incident_channel_views import IncidentNotificationChannelViewSet
from .routing_rule_views import NotificationRoutingRuleViewSet

_router = DefaultRouter()
_router.register(
    r'incident-channels',
    IncidentNotificationChannelViewSet,
    basename='incident-channel',
)
_router.register(
    r'routing-rules',
    NotificationRoutingRuleViewSet,
    basename='routing-rule',
)

urlpatterns = [
    path('', include(_router.urls)),
    # Existing notification endpoints
    path('noti/', NotificationListView.as_view(), name='notification-list'),
    path('<int:pk>/', NotificationDetailView.as_view(), name='notification-detail'),
    path('mark-all-as-read/', MarkAllAsReadView.as_view(), name='mark-all-as-read'),
    path('unread-count/', UnreadCountView.as_view(), name='unread-count'),
    path('notifications/read/', ReadNotificationListView.as_view(), name='read-notification-list'),
    path('notifications/delete-all/', DeleteAllNotificationsView.as_view(), name='delete-all-notifications'),
    
    # New notification management endpoints
    path('preferences/', UserNotificationPreferenceView.as_view(), name='notification-preferences'),
    path('subscriptions/', ProjectSubscriptionListView.as_view(), name='project-subscriptions'),
    path('subscriptions/<int:pk>/', ProjectSubscriptionDetailView.as_view(), name='project-subscription-detail'),
    path('issues/<int:issue_id>/acknowledge/', IssueAcknowledgeView.as_view(), name='issue-acknowledge'),
    path('escalation-rules/', EscalationRuleListView.as_view(), name='escalation-rules'),
    path('escalation-rules/<int:pk>/', EscalationRuleDetailView.as_view(), name='escalation-rule-detail'),
]
