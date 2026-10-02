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


class ZimbraIntegrationConfig(models.Model):
    """Singleton (pk=1) configuration for Zimbra Admin SOAP integration."""

    is_enabled = models.BooleanField(default=False)
    admin_soap_url = models.URLField(
        blank=True,
        default="https://ndejjemail.ndu.ac.ug:7071/service/admin/soap",
        help_text="Zimbra Admin SOAP endpoint.",
    )
    admin_username = models.CharField(max_length=255, blank=True, default="")
    admin_password = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Admin password for SOAP auth. Never returned by the API.",
    )
    domain = models.CharField(max_length=255, blank=True, default="educ.ndu.ac.ug")
    webmail_base_url = models.URLField(
        blank=True,
        default="https://ndejjemail.ndu.ac.ug",
        help_text="Student-facing webmail URL (no trailing slash) used for SSO launch.",
    )
    preauth_key = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Domain preauth key for Zimbra SSO launch (zmprov gdpak <domain> on the mail "
            "server). Never returned by the API. Lets students open webmail from the "
            "student portal without re-entering their Zimbra password."
        ),
    )
    default_password = models.CharField(
        max_length=128,
        blank=True,
        default="NduStudent#2026",
        help_text="Temporary mailbox password; paired with zimbraPasswordMustChange.",
    )
    verify_ssl = models.BooleanField(
        default=True,
        help_text="Verify TLS certificates when calling the Admin SOAP URL.",
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
        verbose_name = "Zimbra integration config"
        verbose_name_plural = "Zimbra integration config"

    def __str__(self):
        return "Zimbra integration"

    @classmethod
    def get_solo(cls) -> "ZimbraIntegrationConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
