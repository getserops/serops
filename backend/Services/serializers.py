from rest_framework import serializers
from Utils.scoped_relations import limit_relations
from .models import Service, SCMService, InfraService, CustomService


class OwnProjectMixin:
    """The ``project`` of a service must be of the requester's organisation:
    without this a member could create a service in, or move one to,
    another organisation's project by sending its id."""

    def get_fields(self):
        from Projects.models import Project
        return limit_relations(super().get_fields(), self.context.get('request'),
                               project=lambda u, org: Project.objects.filter(organisation=org))


class ServiceSerializer(OwnProjectMixin, serializers.ModelSerializer):
    """Base serializer for Service model"""
    class Meta:
        model = Service
        fields = ["id", "project", "name", "description", "category", "status", 
                  "config", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class SCMServiceSerializer(OwnProjectMixin, serializers.ModelSerializer):
    """Serializer for SCM Service (GitLab, GitHub, etc.)"""
    class Meta:
        model = SCMService
        fields = ["id", "project", "name", "description", "category", "status", 
                  "config", "created_at", "updated_at",
                  "provider", "external_id", "external_url", "default_branch",
                  "username", "access_token", "webhook_enabled", "webhook_id",
                  "es_index_name"]
        read_only_fields = ["created_at", "updated_at", "category", "webhook_id"]
        extra_kwargs = {
            "access_token": {"write_only": True}
        }
    
    def validate(self, data):
        provider = data.get("provider")
        external_id = data.get("external_id")
        
        if provider and external_id:
            # Check uniqueness
            existing = SCMService.objects.filter(
                provider=provider, 
                external_id=external_id
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            if existing.exists():
                raise serializers.ValidationError(
                    f"SCM service with provider {provider} and ID {external_id} already exists."
                )
        
        return data


class InfraServiceSerializer(OwnProjectMixin, serializers.ModelSerializer):
    """Serializer for Infrastructure Service"""
    class Meta:
        model = InfraService
        fields = ["id", "project", "name", "description", "category", "status",
                  "config", "created_at", "updated_at",
                  "infra_type", "provider", "host", "port", "connection_string",
                  "health_check_url", "last_health_check", "health_status"]
        read_only_fields = ["created_at", "updated_at", "category", 
                           "last_health_check", "health_status"]
        extra_kwargs = {
            "connection_string": {"write_only": True}
        }


class CustomServiceSerializer(OwnProjectMixin, serializers.ModelSerializer):
    """Serializer for Custom Service"""
    class Meta:
        model = CustomService
        fields = ["id", "project", "name", "description", "category", "status",
                  "config", "created_at", "updated_at",
                  "endpoint_url", "api_key"]
        read_only_fields = ["created_at", "updated_at", "category"]
        extra_kwargs = {
            "api_key": {"write_only": True}
        }


class ServiceListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for listing services"""
    service_type = serializers.SerializerMethodField()
    
    class Meta:
        model = Service
        fields = ["id", "name", "category", "status", "service_type", "created_at"]
    
    def get_service_type(self, obj):
        """Return the specific service type details"""
        specific = obj.get_specific_instance()
        if isinstance(specific, SCMService):
            return {"type": "scm", "provider": specific.provider, "external_id": specific.external_id}
        elif isinstance(specific, InfraService):
            return {"type": "infra", "infra_type": specific.infra_type, "provider": specific.provider}
        elif isinstance(specific, CustomService):
            return {"type": "custom", "endpoint_url": specific.endpoint_url}
        return {"type": "unknown"}
