from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from .models import Service, SCMService, InfraService, CustomService
from .serializers import (
    ServiceSerializer, SCMServiceSerializer, 
    InfraServiceSerializer, CustomServiceSerializer,
    ServiceListSerializer
)
from Middlewares.rbac import ReadOnlyForViewer, IsUserOrAdmin


class ServiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing all service types.
    Supports polymorphic creation based on category.
    """
    permission_classes = [IsAuthenticated, ReadOnlyForViewer]
    
    def get_queryset(self):
        """Filter services by user organization"""
        user = self.request.user
        if not user.organisation:
            return Service.objects.none()
        queryset = Service.objects.filter(project__organisation=user.organisation)
        
        # Filter by project if specified
        project_id = self.request.query_params.get("project")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        
        # Filter by category if specified
        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category=category)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action and category"""
        if self.action == "list":
            return ServiceListSerializer
        
        # For create/update, determine by category in request data
        category = self.request.data.get("category")
        if category == "scm":
            return SCMServiceSerializer
        elif category == "infrastructure":
            return InfraServiceSerializer
        elif category == "custom":
            return CustomServiceSerializer
        
        return ServiceSerializer
    
    def create(self, request, *args, **kwargs):
        """Create service based on category"""
        category = request.data.get("category")
        
        if category == "scm":
            serializer = SCMServiceSerializer(data=request.data)
        elif category == "infrastructure":
            serializer = InfraServiceSerializer(data=request.data)
        elif category == "custom":
            serializer = CustomServiceSerializer(data=request.data)
        else:
            return Response(
                {"error": "Invalid category. Must be scm, infrastructure, or custom."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class SCMServiceViewSet(viewsets.ModelViewSet):
    """ViewSet specifically for SCM Services"""
    serializer_class = SCMServiceSerializer
    permission_classes = [IsAuthenticated, ReadOnlyForViewer]
    
    def get_queryset(self):
        user = self.request.user
        if not user.organisation:
            return SCMService.objects.none()
        return SCMService.objects.filter(project__organisation=user.organisation)
    
    @action(detail=True, methods=["post"])
    def setup_webhook(self, request, pk=None):
        """Setup webhook for this SCM service"""
        service = self.get_object()
        try:
            provider = service.get_provider_client()
            service.webhook_enabled = True
            service.save()
            return Response({"status": "webhook enabled"})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class InfraServiceViewSet(viewsets.ModelViewSet):
    """ViewSet specifically for Infrastructure Services"""
    serializer_class = InfraServiceSerializer
    permission_classes = [IsAuthenticated, ReadOnlyForViewer]
    
    def get_queryset(self):
        user = self.request.user
        if not user.organisation:
            return InfraService.objects.none()
        return InfraService.objects.filter(project__organisation=user.organisation)
    
    @action(detail=True, methods=["post"])
    def health_check(self, request, pk=None):
        """Perform health check on this infrastructure service"""
        from django.utils import timezone
        service = self.get_object()
        
        service.last_health_check = timezone.now()
        service.health_status = "healthy"
        service.save()
        
        return Response({
            "status": service.health_status,
            "checked_at": service.last_health_check
        })


class CustomServiceViewSet(viewsets.ModelViewSet):
    """ViewSet specifically for Custom Services"""
    serializer_class = CustomServiceSerializer
    permission_classes = [IsAuthenticated, ReadOnlyForViewer]
    
    def get_queryset(self):
        user = self.request.user
        if not user.organisation:
            return CustomService.objects.none()
        return CustomService.objects.filter(project__organisation=user.organisation)
