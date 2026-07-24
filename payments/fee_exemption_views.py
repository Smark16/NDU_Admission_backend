"""Staff API: per-student exemptions from scheduled other fees (hostel, etc.)."""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from Programs.permissions import StudentChargesPermission

from payments.fee_exemptions import active_fee_exemptions_for_student, exemption_to_dict
from payments.models import FeeHead, StudentFeeExemption


class StudentFeeExemptionListCreateView(APIView):
    """
    GET  /api/payments/admin/student/<student_id>/fee_exemptions
    POST /api/payments/admin/student/<student_id>/fee_exemptions
    """

    permission_classes = [StudentChargesPermission]

    def get(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)
        active = active_fee_exemptions_for_student(student)
        history = (
            StudentFeeExemption.objects.filter(student=student, is_active=False)
            .select_related("fee_head", "created_by", "revoked_by")
            .order_by("-revoked_at", "-created_at")[:50]
        )
        return Response(
            {
                "student_id": student.student_id,
                "reg_no": student.reg_no,
                "student_name": student.full_name,
                "exemptions": [exemption_to_dict(r) for r in active],
                "revoked": [exemption_to_dict(r) for r in history],
            }
        )

    def post(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)
        fee_head_id = request.data.get("fee_head_id")
        if not fee_head_id:
            return Response({"detail": "fee_head_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        fee_head = get_object_or_404(FeeHead, pk=fee_head_id, is_active=True)
        if fee_head.category == "tuition":
            return Response(
                {
                    "detail": (
                        "Tuition fee heads cannot be exempted here. "
                        "Use scholarships or adjust the tuition schedule."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        year = request.data.get("payable_year_of_study")
        term = request.data.get("payable_term_number")
        try:
            year_i = int(year) if year not in (None, "") else None
            term_i = int(term) if term not in (None, "") else None
        except (TypeError, ValueError):
            return Response(
                {"detail": "payable_year_of_study and payable_term_number must be numbers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if term_i is not None and year_i is None:
            return Response(
                {"detail": "payable_term_number requires payable_year_of_study."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if year_i is not None and year_i < 1:
            return Response({"detail": "payable_year_of_study must be >= 1."}, status=400)
        if term_i is not None and term_i < 1:
            return Response({"detail": "payable_term_number must be >= 1."}, status=400)

        reason = (request.data.get("reason") or "").strip()[:255]

        existing = StudentFeeExemption.objects.filter(
            student=student,
            fee_head=fee_head,
            payable_year_of_study=year_i,
            payable_term_number=term_i,
            is_active=True,
        ).first()
        if existing:
            return Response(
                {"detail": "An active exemption already exists for this fee and scope.", "id": existing.id},
                status=status.HTTP_400_BAD_REQUEST,
            )

        row = StudentFeeExemption.objects.create(
            student=student,
            fee_head=fee_head,
            payable_year_of_study=year_i,
            payable_term_number=term_i,
            reason=reason or "Exempted — student does not use this service",
            created_by=request.user if request.user.is_authenticated else None,
        )
        return Response(exemption_to_dict(row), status=status.HTTP_201_CREATED)


class StudentFeeExemptionRevokeView(APIView):
    """POST /api/payments/admin/fee_exemption/<pk>/revoke"""

    permission_classes = [StudentChargesPermission]

    def post(self, request, pk):
        row = get_object_or_404(
            StudentFeeExemption.objects.select_related("fee_head", "created_by", "revoked_by"),
            pk=pk,
        )
        if not row.is_active:
            return Response({"detail": "Exemption is already revoked."}, status=status.HTTP_400_BAD_REQUEST)
        row.is_active = False
        row.revoked_at = timezone.now()
        row.revoked_by = request.user if request.user.is_authenticated else None
        note = (request.data.get("reason") or "").strip()
        if note:
            row.reason = f"{row.reason} | Revoked: {note}"[:255]
        row.save(update_fields=["is_active", "revoked_at", "revoked_by", "reason"])
        return Response(exemption_to_dict(row))
