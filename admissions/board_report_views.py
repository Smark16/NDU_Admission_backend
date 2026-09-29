"""Board admissions/registration report API (Tables 1-4)."""
from __future__ import annotations

from django.http import HttpResponse
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import user_has_any_erp_perm
from accounts.super_admin import user_is_super_admin

from .board_report import board_report_xlsx, build_board_report
from .models import Batch


class CanViewBoardReport(BasePermission):
    message = "You do not have permission to view this report."

    def has_permission(self, request, view):
        u = request.user
        if not u.is_authenticated:
            return False
        if user_is_super_admin(u):
            return True
        return user_has_any_erp_perm(u, "access_reports")


class BoardReportIntakesView(APIView):
    """Lightweight batch list for the report's intake selector -- scoped to the
    same permission as the report itself, since ListBatch requires a stricter
    Django model permission a reports-only user may not have."""

    permission_classes = [IsAuthenticated, CanViewBoardReport]

    def get(self, request):
        batches = Batch.objects.order_by("-id").values("id", "name", "academic_year", "is_active")
        return Response({"batches": list(batches)})


class BoardReportView(APIView):
    """GET ?batch_id=<id> -- Tables 1-4 for that intake. ?output=xlsx to export."""

    permission_classes = [IsAuthenticated, CanViewBoardReport]

    def get(self, request):
        try:
            batch_id = int(request.query_params.get("batch_id") or 0)
        except (TypeError, ValueError):
            batch_id = 0
        if not batch_id:
            return Response({"detail": "batch_id is required."}, status=400)
        if not Batch.objects.filter(pk=batch_id).exists():
            return Response({"detail": "Batch not found."}, status=404)

        payload = build_board_report(batch_id)

        # Not "format" -- DRF's DefaultContentNegotiation treats ?format=<x> as its own
        # renderer-selection override and raises Http404 when no renderer matches "xlsx".
        if (request.query_params.get("output") or "").strip().lower() == "xlsx":
            safe_name = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in payload["batch"]["name"])
            response = HttpResponse(
                board_report_xlsx(payload),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="admissions_registration_report_{safe_name[:60]}.xlsx"'
            return response
        return Response(payload)
