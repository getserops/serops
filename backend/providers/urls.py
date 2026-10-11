from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProjectList, ProjectDetail, SetupGitLabWebhookView,
    DeleteGitLabWebhookView, VerifyGitLabProjectView, PipelineLogsView,
    VerifyGitHubProjectView, VerifyBitbucketProjectView, VerifyAzureDevOpsProjectView,
    ProviderIntegrationViewSet, PipelineListView, DeploymentListView,
)
from .gitlab_webhook import GitLabCICDWebhookHandler
from .deployment_webhook import GenericDeploymentWebhookHandler
from .argocd_webhook import ArgoCDDeploymentWebhookHandler
from .flux_webhook import FluxDeploymentWebhookHandler

router = DefaultRouter()
router.register(r'integrations', ProviderIntegrationViewSet, basename='provider-integration')

urlpatterns = [
    path('', ProjectList.as_view()),
    path('<int:pk>/', ProjectDetail.as_view()),
    path('webhook/', GitLabCICDWebhookHandler.as_view()),
    # Generic deploy webhook — for ArgoCD Notifications, Flux, Helm hooks,
    # Terraform apply post-hooks, kubectl rollout wrappers. Uses the same
    # CICDBinding.binding_id identity pattern as CI/CD webhooks; the payload
    # is a minimal {commit_sha, environment, ...} shape rather than a
    # provider-specific pipeline event.
    path(
        'webhook/deployment/<int:binding_id>/',
        GenericDeploymentWebhookHandler.as_view(),
        name='generic-deployment-webhook',
    ),
    # Native GitOps webhook handlers — accept the vendor's own
    # notification payload (ArgoCD Notifications, Flux Notification
    # Controller) so users don't need to author custom templates.
    # Both subclass GenericDeploymentWebhookHandler for shared auth +
    # rate limiting + deployment persistence.
    path(
        'webhook/argocd/<int:binding_id>/',
        ArgoCDDeploymentWebhookHandler.as_view(),
        name='argocd-deployment-webhook',
    ),
    path(
        'webhook/flux/<int:binding_id>/',
        FluxDeploymentWebhookHandler.as_view(),
        name='flux-deployment-webhook',
    ),
    path('webhook-set/', SetupGitLabWebhookView.as_view()),
    path('webhook-del/', DeleteGitLabWebhookView.as_view()),
    path('verify-project/', VerifyGitLabProjectView.as_view(), name='verify_gitlab_project'),
    path('verify-github/', VerifyGitHubProjectView.as_view(), name='verify_github_project'),
    path('verify-bitbucket/', VerifyBitbucketProjectView.as_view(), name='verify_bitbucket_project'),
    path('verify-azure-devops/', VerifyAzureDevOpsProjectView.as_view(), name='verify_azure_devops_project'),
    path('<int:project_id>/pipelines/<int:pipeline_id>/logs/', PipelineLogsView.as_view(), name='pipeline_logs'),
    path('pipelines/', PipelineListView.as_view(), name='pipeline-list'),
    path('deployments/', DeploymentListView.as_view(), name='deployment-list'),
    path('', include(router.urls)),
]