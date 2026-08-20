"""Staff scan desk API — purpose-gated live verify from one student QR."""
from __future__ import annotations

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import CanVerifyStudentCardPermission

from .scan_desk import run_scan_desk


class StudentCardScanDeskView(APIView):
    """
    GET /api/payments/scan_desk?code=…&purpose=id|registration|exam

    Same plastic ID QR (paycode / student number). Desk purpose selects
    which live Steward report to show.
    """

    permission_classes = [IsAuthenticated, CanVerifyStudentCardPermission]

    def get(self, request):
        code = (request.query_params.get("code") or "").strip()
        purpose = request.query_params.get("purpose") or "registration"
        if not code:
            return Response(
                {
                    "valid": False,
                    "verdict": "deny",
                    "detail": "Missing scan code.",
                    "message": "DENY — Missing scan code.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        payload, http_status = run_scan_desk(
            code=code, purpose=purpose, request=request
        )
        return Response(payload, status=http_status)
