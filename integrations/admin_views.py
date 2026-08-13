"""Super-Admin JWT APIs for Moodle integration configuration."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import IsSuperAdminOnly

from .api_keys import api_key_prefix, generate_moodle_api_key, hash_api_key
from .models import MoodleIntegrationConfig


def _config_payload(cfg: MoodleIntegrationConfig, *, plaintext_key: str | None = None) -> dict:
    payload = {
        "is_enabled": cfg.is_enabled,
        "moodle_base_url": cfg.moodle_base_url or "",
        "cleared_min_percent": float(cfg.cleared_min_percent),
        "partial_min_percent": float(cfg.partial_min_percent),
        "api_key_configured": bool(cfg.api_key_hash),
        "api_key_prefix": cfg.api_key_prefix or "",
        "api_key_masked": f"{cfg.api_key_prefix}…" if cfg.api_key_prefix else "",
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }
    if plaintext_key:
        payload["api_key"] = plaintext_key
        payload["api_key_once"] = True
    return payload


class MoodleConfigView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def get(self, request):
        cfg = MoodleIntegrationConfig.get_solo()
        return Response(_config_payload(cfg))

    def patch(self, request):
        cfg = MoodleIntegrationConfig.get_solo()
        data = request.data or {}

        if "is_enabled" in data:
            cfg.is_enabled = bool(data.get("is_enabled"))

        if "moodle_base_url" in data:
            cfg.moodle_base_url = (data.get("moodle_base_url") or "").strip()

        for field in ("cleared_min_percent", "partial_min_percent"):
            if field not in data:
                continue
            try:
                val = Decimal(str(data.get(field)))
            except (InvalidOperation, TypeError, ValueError):
                return Response(
                    {"detail": f"{field} must be a number."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if val < 0 or val > 100:
                return Response(
                    {"detail": f"{field} must be between 0 and 100."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            setattr(cfg, field, val)

        if cfg.partial_min_percent > cfg.cleared_min_percent:
            return Response(
                {"detail": "partial_min_percent cannot be greater than cleared_min_percent."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cfg.updated_by = request.user
        cfg.save()
        return Response(_config_payload(cfg))


class MoodleRotateKeyView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def post(self, request):
        cfg = MoodleIntegrationConfig.get_solo()
        raw = generate_moodle_api_key()
        cfg.api_key_prefix = api_key_prefix(raw)
        cfg.api_key_hash = hash_api_key(raw)
        cfg.updated_by = request.user
        cfg.save(update_fields=["api_key_prefix", "api_key_hash", "updated_by", "updated_at"])
        return Response(
            {
                **_config_payload(cfg, plaintext_key=raw),
                "detail": "New API key generated. Copy it now — it will not be shown again.",
            }
        )
