from django.contrib import admin

from .models import MoodleApiAccessLog, MoodleIntegrationConfig, ZimbraIntegrationConfig


@admin.register(MoodleIntegrationConfig)
class MoodleIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "is_enabled",
        "api_key_prefix",
        "cleared_min_percent",
        "partial_min_percent",
        "updated_at",
    )
    readonly_fields = ("api_key_prefix", "api_key_hash", "updated_at")


@admin.register(MoodleApiAccessLog)
class MoodleApiAccessLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "endpoint", "http_status", "key_prefix", "detail")
    list_filter = ("http_status", "endpoint")
    search_fields = ("endpoint", "detail", "key_prefix")
    readonly_fields = ("endpoint", "key_prefix", "http_status", "detail", "created_at")


@admin.register(ZimbraIntegrationConfig)
class ZimbraIntegrationConfigAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "is_enabled",
        "admin_soap_url",
        "admin_username",
        "domain",
        "verify_ssl",
        "updated_at",
    )
    readonly_fields = ("updated_at",)
    exclude = ("admin_password",)
