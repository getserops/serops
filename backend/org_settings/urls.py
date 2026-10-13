"""
URL configuration for Organisation Settings API.
"""

from django.urls import path
from .views import (
    TestWebhookView,
    AIModelProvidersView,
    AIModelProviderDetailView,
    AvailableModelsView,
    AISettingsView,
    AIBudgetStatusView,
    OllamaProbeView,
    APIKeysView,
    TestAIConnectionView,
    IssueSettingsView,
    SentinelConfigView,
)

urlpatterns = [
    # PR-N phase 2 (2026-09-26): NotificationSettings retired.
    # Delivery targets → /api/notifications/incident-channels/
    # Routing rules   → /api/notifications/routing-rules/
    # This endpoint is preserved ONLY for the webhook-test button.
    path('notifications/test/', TestWebhookView.as_view(), name='test-webhook'),

    # AI settings
    path('ai/', AISettingsView.as_view(), name='ai-settings'),
    path('ai/providers/', AIModelProvidersView.as_view(), name='ai-providers'),
    path('ai/providers/<int:pk>/', AIModelProviderDetailView.as_view(), name='ai-provider-detail'),
    path('ai/available-models/', AvailableModelsView.as_view(), name='available-models'),
    path('ai/test/', TestAIConnectionView.as_view(), name='test-ai-connection'),
    # Q3.3 — read-only spend snapshot for the settings UI.
    path('ai/budget/', AIBudgetStatusView.as_view(), name='ai-budget-status'),
    # Q4.1 — reachability + model listing for Ollama endpoints.
    path('ai/ollama/probe/', OllamaProbeView.as_view(), name='ollama-probe'),

    # API Keys
    path('api-keys/', APIKeysView.as_view(), name='api-keys'),
    path('api-keys/<int:provider_id>/', APIKeysView.as_view(), name='api-key-detail'),

    # Issue deduplication settings
    path('issues/', IssueSettingsView.as_view(), name='issue-settings'),

    # Sentinel configuration
    path('sentinel/', SentinelConfigView.as_view(), name='sentinel-config'),

    # NOTE: System mail settings were removed 2026-09-01. SMTP is now
    # env-only (Grafana model): configure EMAIL_HOST etc. in your .env
    # and restart the backend. Verify with `python manage.py check_smtp
    # <recipient>`.
]
