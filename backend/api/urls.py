from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse
from django.db import connection
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi


def health_check(request):
    """Unauthenticated health check for deployment verification."""
    try:
        connection.ensure_connection()
        return JsonResponse({'status': 'ok'})
    except Exception:
        return JsonResponse({'status': 'error', 'detail': 'database unavailable'}, status=503)


def version_endpoint(request):
    """Unauthenticated version endpoint (Batch 43, SemVer discipline).

    Every mature self-hosted OSS exposes this in some form (Grafana:
    /api/health, Prometheus: /api/v1/status/buildinfo, Metabase:
    /api/session/properties, n8n: /rest/settings). Purpose:

    * Support debugging — a user filing an issue tells us exactly what
      version they're running without shelling into the container.
    * Upgrade planning — ops teams can script "which of my instances
      are still on 1.2.x".
    * Post-restore verification — after a Batch-27 backup restore,
      confirm the image tag matches the DB migration state.

    Payload is deliberately narrow: version + git sha + built-at.
    No admin-only fields (env vars, DB stats) — that's what
    ``/metrics/`` and the audit log are for.
    """
    from api.version import version_info
    return JsonResponse(version_info())

# Import webhook handlers for CI/CD providers
from providers.github_webhook import GitHubActionsWebhookHandler
from providers.jenkins_webhook import JenkinsWebhookHandler
from providers.bitbucket_webhook import BitbucketWebhookHandler
from providers.azure_devops_webhook import AzureDevOpsWebhookHandler
from providers.gitlab_webhook import GitLabCICDWebhookHandler
from Projects.views import SCMWebhookReceiverView
from Data.alert_webhooks import AlertWebhookView
from Data.self_metrics import MetricsView

schema_view = get_schema_view(
   openapi.Info(
      title="Serops Log Retrieval API",
      default_version='v1',
      description="API documentation for Serops Log Retrieval system",
      terms_of_service="https://www.google.com/policies/terms/",
      contact=openapi.Contact(email="contact@serops.ai"),
      license=openapi.License(name="BSD License"),
   ),
   public=True,
   permission_classes=[permissions.AllowAny],
)

api_urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('version/', version_endpoint, name='version'),
    path('admin/', admin.site.urls),
    path('auth/', include('Users.urls')),
    path('organisation/', include('Organisations.urls')),
    path('chat/', include('ai_model.urls')),
    path('data/', include('Data.urls')),
    path('providers/', include('providers.urls')),  # Renamed from gitlab/
    path('notification/', include('notifications.urls')),
    path('projects/', include('Projects.urls')),
    path('services/', include('Services.urls')),  # Polymorphic services API
    path('settings/', include('org_settings.urls')),  # Organisation settings API
    path('utils/', include('Utils.urls')),  # Utility endpoints
    path('integrations/', include('integrations.urls')),  # Log/metric provider management
    path('traces/', include('traces.urls')),  # Distributed tracing (OTLP receiver + IngestKey CRUD)

    path('webhooks/scm/<int:binding_id>/', SCMWebhookReceiverView.as_view(), name='scm-webhook'),

    # Multi-provider CI/CD webhooks — binding_id is REQUIRED so the
    # server can look up the binding-specific secret and enforce HMAC
    # validation. Legacy unbound URLs were dropped for security; any
    # webhooks registered under the old paths must be re-registered.
    path('webhooks/gitlab/<int:binding_id>/', GitLabCICDWebhookHandler.as_view(), name='gitlab-webhook-bound'),
    path('webhooks/github/<int:binding_id>/', GitHubActionsWebhookHandler.as_view(), name='github-webhook-bound'),
    path('webhooks/jenkins/<int:binding_id>/', JenkinsWebhookHandler.as_view(), name='jenkins-webhook-bound'),
    path('webhooks/bitbucket/<int:binding_id>/', BitbucketWebhookHandler.as_view(), name='bitbucket-webhook-bound'),
    path('webhooks/azure-devops/<int:binding_id>/', AzureDevOpsWebhookHandler.as_view(), name='azure-devops-webhook-bound'),

    # Alert webhooks (Item #13) — bearer secret via
    # settings.ALERT_WEBHOOK_SECRETS[<source>]. Org-scoped by URL so a
    # leaked secret only affects one tenant.
    path('webhooks/alerts/<str:source>/<int:org_id>/', AlertWebhookView.as_view(), name='alert-webhook'),

    # Swagger URLs
    path('docs/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
]

urlpatterns = [
    path('api/', include(api_urlpatterns)),
    # Self-metrics — Prometheus exposition. Root URL (not under /api/)
    # to follow the SRE convention. Optional basic-auth via
    # SEROPS_METRICS_BASIC_AUTH env.
    path('metrics/', MetricsView.as_view(), name='self-metrics'),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
