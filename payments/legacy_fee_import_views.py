"""Staff API: list / delete fee-balance import (legacy) payment rows."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.permissions import StudentChargesPermission

from .legacy_fee_import_cleanup import (
    delete_legacy_fee_rows,
    list_legacy_fee_rows,
    list_students_with_legacy_fee_imports,
)


class LegacyFeeImportIndexView(APIView):
    """
    GET /api/payments/admin/legacy_fee_imports/
    Lists students that still have LEGACY-PAID / LEGACY-DUE import rows.
    """

    permission_classes = [StudentChargesPermission]

    def get(self, request):
        try:
            limit = min(max(int(request.query_params.get("limit") or 100), 1), 500)
        except (TypeError, ValueError):
            limit = 100
        students = list_students_with_legacy_fee_imports(limit=limit)
        return Response(
            {
                "students": students,
                "student_count": len(students),
                "total_rows": sum(int(s.get("row_count") or 0) for s in students),
            }
        )


class StudentLegacyFeeImportListDeleteView(APIView):
    """
    GET    /api/payments/admin/student/<student_id>/legacy_fee_imports/
    DELETE /api/payments/admin/student/<student_id>/legacy_fee_imports/
           body: { "confirm": true, "ids": [optional…] }
           Omit ids (or send []) to delete all legacy import rows for the student.
    """

    permission_classes = [StudentChargesPermission]

    def get(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id, is_admitted=True)
        rows = list_legacy_fee_rows(student)
        return Response(
            {
                "student_id": student.student_id,
                "reg_no": student.reg_no,
                "student_name": getattr(student, "full_name", None) or student.reg_no,
                "legacy_fee_imports": rows,
                "total_count": len(rows),
            }
        )

    def delete(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id, is_admitted=True)
        confirm = request.data.get("confirm")
        if confirm is not True and str(confirm).lower() not in ("true", "1", "yes"):
            return Response(
                {
                    "detail": (
                        'Send JSON body {"confirm": true} to delete legacy fee imports. '
                        'Optional "ids": [int, ...] to delete selected rows only.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_ids = request.data.get("ids", None)
        payment_ids: list[int] | None
        if raw_ids is None:
            payment_ids = None
        elif isinstance(raw_ids, list):
            if not raw_ids:
                payment_ids = None
            else:
                try:
                    payment_ids = [int(i) for i in raw_ids]
                except (TypeError, ValueError):
                    return Response(
                        {"detail": "ids must be a list of integers."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        else:
            return Response(
                {"detail": "ids must be a list of integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = delete_legacy_fee_rows(
                student,
                payment_ids=payment_ids,
                deleted_by=request.user,
                request=request,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "detail": (
                    f"Deleted {result['deleted_count']} legacy fee-import row(s). "
                    "SchoolPay payments were not changed."
                ),
                **result,
                "legacy_fee_imports": list_legacy_fee_rows(student),
            },
            status=status.HTTP_200_OK,
        )
