from django.contrib import admin
from .models import Service, SCMService, InfraService, CustomService


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "category", "status", "created_at"]
    list_filter = ["category", "status"]
    search_fields = ["name", "project__name"]


@admin.register(SCMService)
class SCMServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "provider", "external_id", "webhook_enabled", "status"]
    list_filter = ["provider", "webhook_enabled", "status"]
    search_fields = ["name", "project__name", "external_id"]


@admin.register(InfraService)
class InfraServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "infra_type", "provider", "host", "health_status"]
    list_filter = ["infra_type", "provider", "health_status"]
    search_fields = ["name", "project__name", "host"]


@admin.register(CustomService)
class CustomServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "endpoint_url", "status"]
    list_filter = ["status"]
    search_fields = ["name", "project__name", "endpoint_url"]
