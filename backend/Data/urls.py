from django.urls import path
from .views import BatchAnalysisHistoryView, BatchIssuesView, BatchPostmortemView, BatchPromoteAnalysisView, BatchReanalyzeView, BatchTimelineView, DeleteOldBatchesView, FluentdLogView, HostDiscoveryView, MetricCorrelationView, IssueListView, IssueActionsView, IssueBulkActionsView, LogBatchView, NodeMemoryRawView, BatchDetailView ,RecommendationStatsView,IssueStatsView, NodeCPURawView, SimilarIssuesView, SystemHealthView, ServiceReliabilityView, TrendAnalysisView
from .investigation_views import InvestigationDetailView, InvestigationListView, InvestigationOptionsView
from .dashboard_views import MTTRView, ServiceHealthView as ServiceHealthMapView, RootCauseStatsView, RecentDeploymentsView, CorrelationInsightsView, RecentAnalysisFeedView, SentinelStatsView
from .settings_views import SecuritySettingsView, AuditLogView, AuditLogExportView, DataUsageView, RetentionPolicyView  # Enterprise features

urlpatterns = [
    path('hosts/', HostDiscoveryView.as_view(), name='host-discovery'),
    path('batches/<str:batch_id>/correlations/', MetricCorrelationView.as_view(), name='metric-correlation'),
    path('logs', FluentdLogView.as_view(), name='fluentd-logs'),
    path('batches',LogBatchView.as_view(),name="Batches"),
    path('metrics', NodeMemoryRawView.as_view(), name='node-memory-swap'),
    # IMPORTANT: Specific routes must come BEFORE the catch-all <str:batch_id> route
    path('batches/reanalyze/', BatchReanalyzeView.as_view(), name='batch-reanalyze'),
    path('investigations/', InvestigationListView.as_view(), name='investigations'),
    path('investigations/options/', InvestigationOptionsView.as_view(), name='investigation-options'),
    path('investigations/<int:pk>/', InvestigationDetailView.as_view(), name='investigation-detail'),
    path('batches/<str:batch_id>/history/', BatchAnalysisHistoryView.as_view(), name='batch-analysis-history'),
    path('batches/<str:batch_id>/promote-analysis/', BatchPromoteAnalysisView.as_view(), name='batch-promote-analysis'),
    path('batches/<str:batch_id>/timeline/', BatchTimelineView.as_view(), name='batch-timeline'),
    path('batches/<str:batch_id>/postmortem/', BatchPostmortemView.as_view(), name='batch-postmortem'),
    path('batches/<str:batch_id>/', BatchDetailView.as_view(), name='batch-detail'),
    path('recommendation-stats/', RecommendationStatsView.as_view(), name='recommendation-stats'),
    path('issue-stats/', IssueStatsView.as_view(), name='issue-stats'),
    path('issues/',IssueListView.as_view(), name='issues-list'),
    path('issues/bulk-action/', IssueBulkActionsView.as_view(), name='issue-bulk-action'),
    path('issues/<int:issue_id>/similar/', SimilarIssuesView.as_view(), name='issue-similar'),
    path('issues/<int:issue_id>/<str:action>/', IssueActionsView.as_view(), name='issue-action'),
    path('issues/<str:batch_id>/', BatchIssuesView.as_view(), name='batch-issues'),
    path('cpu/raw/', NodeCPURawView.as_view(), name='node-cpu-raw'),
    path('delete-old-batches/', DeleteOldBatchesView.as_view(), name='delete-old-batches'),
    path('analytics/health/', SystemHealthView.as_view(), name='system-health'),
    path('analytics/services/', ServiceReliabilityView.as_view(), name='service-reliability'),
    path('analytics/trends/', TrendAnalysisView.as_view(), name='issue-trends'),
    # Phase 4: Dashboard enhancements
    path('analytics/mttr/', MTTRView.as_view(), name='mttr-stats'),
    path('analytics/service-health/', ServiceHealthMapView.as_view(), name='service-health-map'),
    path('analytics/root-causes/', RootCauseStatsView.as_view(), name='root-cause-stats'),
    path('analytics/deployments/', RecentDeploymentsView.as_view(), name='recent-deployments'),
    path('analytics/correlations/', CorrelationInsightsView.as_view(), name='correlation-insights'),
    path('analytics/feed/', RecentAnalysisFeedView.as_view(), name='analysis-feed'),
    path('analytics/sentinel/', SentinelStatsView.as_view(), name='sentinel-stats'),
    # Enterprise features: Security, Audit, Data Management
    path('settings/security/', SecuritySettingsView.as_view(), name='security-settings'),
    path('settings/audit-log/', AuditLogView.as_view(), name='audit-log'),
    path('settings/audit-log/export/', AuditLogExportView.as_view(), name='audit-log-export'),
    path('settings/data-usage/', DataUsageView.as_view(), name='data-usage'),
    path('settings/retention-policy/', RetentionPolicyView.as_view(), name='retention-policy'),
]