from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models


class MoodleIntegrationConfig(models.Model):
    """Singleton (pk=1) configuration for Moodle LMS integration."""

    is_enabled = models.BooleanField(default=False)
    api_key_prefix = models.CharField(max_length=16, blank=True, default="")
    api_key_hash = models.CharField(max_length=64, blank=True, default="")
    launch_signing_secret = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Shared secret for STEWARD→Moodle SSO launch HMAC "
            "(same value Moodle uses to verify sig). Set automatically when rotating the API key."
        ),
    )
    moodle_base_url = models.URLField(blank=True, default="")
    cleared_min_percent = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal("100.0"),
        help_text="Minimum tuition % paid for CLEARED status.",
    )
    partial_min_percent = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal("50.0"),
        help_text="Minimum tuition % paid for PARTIAL status (below CLEARED).",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "Moodle integration config"
        verbose_name_plural = "Moodle integration config"

    def __str__(self):
        return "Moodle integration"

    @classmethod
    def get_solo(cls) -> "MoodleIntegrationConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MoodleApiAccessLog(models.Model):
    """Light audit trail for Moodle-facing API calls."""

    endpoint = models.CharField(max_length=120)
    key_prefix = models.CharField(max_length=16, blank=True, default="")
    http_status = models.PositiveSmallIntegerField(default=200)
    detail = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Moodle API access log"
        verbose_name_plural = "Moodle API access logs"

    def __str__(self):
        return f"{self.endpoint} {self.http_status} @ {self.created_at}"
