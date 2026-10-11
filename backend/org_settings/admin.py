"""
Admin configuration for Organisation Settings.
"""

from django.contrib import admin
from .models import (
    AIModelProvider,
    OrganisationAISettings,
    OrganisationAPIKey,
)


@admin.register(AIModelProvider)
class AIModelProviderAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'is_active', 'requires_api_key', 'default_model']
    list_filter = ['is_active', 'requires_api_key']
    search_fields = ['name', 'display_name']


@admin.register(OrganisationAISettings)
class OrganisationAISettingsAdmin(admin.ModelAdmin):
    list_display = ['organisation', 'default_provider', 'fallback_provider', 'use_custom_keys', 'updated_at']
    list_filter = ['default_provider', 'use_custom_keys']
    search_fields = ['organisation__name']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(OrganisationAPIKey)
class OrganisationAPIKeyAdmin(admin.ModelAdmin):
    list_display = ['organisation', 'provider', 'is_active', 'last_tested_at', 'last_test_success']
    list_filter = ['provider', 'is_active', 'last_test_success']
    search_fields = ['organisation__name']
    readonly_fields = ['created_at', 'updated_at', 'last_tested_at', 'last_test_success']
    
    def get_masked_key(self, obj):
        return obj.get_masked_key()
    get_masked_key.short_description = 'API Key'
