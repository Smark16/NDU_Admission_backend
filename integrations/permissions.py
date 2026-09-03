import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission

from .api_keys import api_keys_match
from .models import MoodleIntegrationConfig


class HasEvotingApiKey(BasePermission):
    """E-voting server-to-server: X-API-Key must match EVOTING_API_KEY."""

    message = "Invalid or missing e-voting API key."

    def has_permission(self, request, view):
        expected = (getattr(settings, "EVOTING_API_KEY", None) or "").strip()
        raw = (request.headers.get("X-API-Key") or request.META.get("HTTP_X_API_KEY") or "").strip()
        if not expected or not raw:
            return False
        return hmac.compare_digest(raw, expected)


class HasMoodleApiKey(BasePermission):
    """Moodle service calls: require enabled config + valid X-API-Key."""

    message = "Invalid or missing Moodle API key."

    def has_permission(self, request, view):
        raw = (request.headers.get("X-API-Key") or request.META.get("HTTP_X_API_KEY") or "").strip()
        if not raw:
            self.message = "Missing X-API-Key header."
            return False
        cfg = MoodleIntegrationConfig.get_solo()
        if not cfg.is_enabled:
            self.message = "Moodle integration is disabled."
            return False
        if not cfg.api_key_hash:
            self.message = "Moodle API key is not configured."
            return False
        if not api_keys_match(raw, cfg.api_key_hash):
            self.message = "Invalid Moodle API key."
            return False
        request.moodle_api_key_prefix = cfg.api_key_prefix
        return True
