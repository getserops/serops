from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ServiceViewSet, SCMServiceViewSet, 
    InfraServiceViewSet, CustomServiceViewSet
)

router = DefaultRouter()
router.register(r"all", ServiceViewSet, basename="service")
router.register(r"scm", SCMServiceViewSet, basename="scm-service")
router.register(r"infra", InfraServiceViewSet, basename="infra-service")
router.register(r"custom", CustomServiceViewSet, basename="custom-service")

urlpatterns = [
    path("", include(router.urls)),
]
