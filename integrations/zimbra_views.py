"""Super-Admin JWT APIs for Zimbra email integration."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import IsSuperAdminOnly

from . import zimbra_client, zimbra_provisioning
from .models import ZimbraIntegrationConfig


def _config_payload(cfg: ZimbraIntegrationConfig) -> dict:
    return {
        "is_enabled": cfg.is_enabled,
        "admin_soap_url": cfg.admin_soap_url or "",
        "admin_username": cfg.admin_username or "",
        "admin_password_configured": bool((cfg.admin_password or "").strip()),
        "domain": cfg.domain or "",
        "default_password": cfg.default_password or "",
        "verify_ssl": bool(cfg.verify_ssl),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


class ZimbraConfigView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def get(self, request):
        cfg = ZimbraIntegrationConfig.get_solo()
        return Response(_config_payload(cfg))

    def patch(self, request):
        cfg = ZimbraIntegrationConfig.get_solo()
        data = request.data or {}

        if "is_enabled" in data:
            cfg.is_enabled = bool(data.get("is_enabled"))

        if "admin_soap_url" in data:
            cfg.admin_soap_url = (data.get("admin_soap_url") or "").strip()

        if "admin_username" in data:
            cfg.admin_username = (data.get("admin_username") or "").strip()

        if "admin_password" in data:
            pwd = data.get("admin_password")
            # Omit / null / blank keeps existing password; non-empty replaces.
            if pwd is not None and str(pwd).strip() != "":
                cfg.admin_password = str(pwd)

        if "domain" in data:
            cfg.domain = (data.get("domain") or "").strip().lower()

        if "default_password" in data:
            val = (data.get("default_password") or "").strip()
            if val:
                cfg.default_password = val

        if "verify_ssl" in data:
            cfg.verify_ssl = bool(data.get("verify_ssl"))

        cfg.updated_by = request.user
        cfg.save()
        return Response(_config_payload(cfg))


class ZimbraTestConnectionView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def post(self, request):
        cfg = ZimbraIntegrationConfig.get_solo()
        try:
            result = zimbra_client.test_connection(cfg)
            return Response(result)
        except zimbra_client.ZimbraConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except zimbra_client.ZimbraRequestError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class ZimbraImportMappingView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def post(self, request):
        data = request.data or {}
        rows = data.get("mappings") or data.get("rows") or data
        if not isinstance(rows, list):
            return Response(
                {"detail": "Send a JSON list of {reg_no, university_email} (or {mappings: [...]})."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(rows) > 10000:
            return Response({"detail": "Too many rows (max 10000)."}, status=status.HTTP_400_BAD_REQUEST)
        result = zimbra_provisioning.import_university_email_mapping(rows)
        return Response({"detail": "Import finished.", **result})


class ZimbraProvisionView(APIView):
    permission_classes = [IsAuthenticated, IsSuperAdminOnly]

    def post(self, request):
        data = request.data or {}
        reg_no = (data.get("reg_no") or "").strip() or None
        admission_id = data.get("admission_id")
        try:
            admission_id = int(admission_id) if admission_id not in (None, "") else None
        except (TypeError, ValueError):
            return Response({"detail": "admission_id must be an integer."}, status=status.HTTP_400_BAD_REQUEST)

        notify = bool(data.get("notify"))
        channel = (data.get("channel") or "both").strip().lower()
        title = (data.get("title") or "").strip() or None
        message = (data.get("message") or data.get("body") or "").strip() or None

        try:
            student = zimbra_provisioning.resolve_student(reg_no=reg_no, admission_id=admission_id)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = zimbra_provisioning.provision_student(
                student,
                notify=notify,
                channel=channel,
                title=title,
                message=message,
            )
        except zimbra_client.ZimbraConfigError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except zimbra_client.ZimbraRequestError as exc:
            return Response(
                {"detail": str(exc), "code": exc.code},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({"detail": "Provisioned.", **result})
