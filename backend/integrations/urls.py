"""
URL configuration for Integrations API.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ClusterViewSet, ObservabilityIntegrationViewSet

router = DefaultRouter()
router.register(
    r'observability',
    ObservabilityIntegrationViewSet,
    basename='observability-integration',
)
router.register(r'clusters', ClusterViewSet, basename='cluster')

urlpatterns = [
    path('', include(router.urls)),
]
