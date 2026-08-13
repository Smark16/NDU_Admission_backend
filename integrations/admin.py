from django.contrib import admin

from .models import MoodleApiAccessLog, MoodleIntegrationConfig


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
