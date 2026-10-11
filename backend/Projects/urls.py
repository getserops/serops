from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ProjectListView,
    ProjectDetailView,
    ProjectServiceView,
    ProjectServiceDetailView,
    CustomServiceView,
    SCMBindingViewSet,
    CICDBindingViewSet,
    ProjectDeploymentViewSet,
)

# Router for ViewSets
router = DefaultRouter()
router.register(r'scm-bindings', SCMBindingViewSet, basename='scm-binding')
router.register(r'cicd-bindings', CICDBindingViewSet, basename='cicd-binding')
router.register(r'deployments', ProjectDeploymentViewSet, basename='project-deployment')

urlpatterns = [
    path('', ProjectListView.as_view(), name='project-list'),
    path('<int:pk>/', ProjectDetailView.as_view(), name='project-detail'),
    path('<int:project_id>/services/', ProjectServiceView.as_view(), name='project-service-create'),
    path('services/<int:pk>/', ProjectServiceDetailView.as_view(), name='project-service-detail'),
    path('<int:project_id>/custom-services/', CustomServiceView.as_view(), name='project-custom-services'),
    # Include router URLs for bindings
    path('', include(router.urls)),
]
