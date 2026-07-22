"""Admin portal-account toggle and document PDF downloads for bonafide students."""
from __future__ import annotations

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import assert_admitted_student_access, filter_admitted_students_for_user
from admissions.models import AdmittedStudent, StudentPortalAccountAction
from audit.utils import log_audit_event


def _get_bonafide_student(request, pk: int) -> AdmittedStudent | None:
    qs = filter_admitted_students_for_user(
        AdmittedStudent.objects.filter(is_admitted=True, pk=pk).select_related(
            "student_user",
            "application",
            "admitted_program",
        ),
        request.user,
    )
    return qs.first()


def _require_view_admitted(user) -> bool:
    return user.has_perm("admissions.view_admittedstudent")


class BonafidePortalAccountToggleView(APIView):
    """POST: activate or deactivate the student's portal login (with required reason)."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not _require_view_admitted(request.user):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        student = _get_bonafide_student(request, pk)
        if not student:
            return Response({"detail": "Student not found."}, status=status.HTTP_404_NOT_FOUND)
        assert_admitted_student_access(request.user, student)

        portal_user = student.student_user
        if not portal_user:
            return Response(
                {
                    "detail": (
                        "This student has no portal login yet. "
                        "Provision the student account first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data or {}
        if "is_active" not in data:
            return Response(
                {"detail": "is_active (true/false) is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        want_active = bool(data.get("is_active"))
        reason = (data.get("reason") or "").strip()
        if len(reason) < 5:
            return Response(
                {"detail": "A reason of at least 5 characters is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if portal_user.is_active == want_active:
            state = "active" if want_active else "inactive"
            return Response(
                {"detail": f"Portal account is already {state}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        action = (
            StudentPortalAccountAction.ACTION_ACTIVATE
            if want_active
            else StudentPortalAccountAction.ACTION_DEACTIVATE
        )

        with transaction.atomic():
            portal_user.is_active = want_active
            portal_user.save(update_fields=["is_active"])
            StudentPortalAccountAction.objects.create(
                student=student,
                portal_user=portal_user,
                action=action,
                reason=reason,
                performed_by=request.user,
            )

        log_audit_event(
            request.user,
            f"portal_{action}",
            obj=student,
            description=(
                f"Portal account {action} for {student.reg_no}: {reason[:400]}"
            ),
            request=request,
        )

        from admissions.bonafide_portal import build_bonafide_portal_snapshot

        # Return refreshed portal_account block
        snap = build_bonafide_portal_snapshot(student, request)
        return Response(
            {
                "detail": (
                    f"Portal account {'activated' if want_active else 'deactivated'}."
                ),
                "portal_account": snap.get("portal_account"),
            }
        )


class BonafideTranscriptPdfView(APIView):
    """Admin: download provisional results / transcript PDF for a bonafide student."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _require_view_admitted(request.user):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        student = _get_bonafide_student(request, pk)
        if not student:
            return Response({"detail": "Student not found."}, status=status.HTTP_404_NOT_FOUND)
        assert_admitted_student_access(request.user, student)

        from examinations.services.graduation_status import graduation_show_scores_default
        from examinations.services.provisional_results_pdf import render_provisional_results_pdf

        show_param = request.query_params.get("show_scores")
        if show_param is None:
            show_scores = graduation_show_scores_default(student)
        else:
            show_scores = show_param.lower() in ("1", "true", "yes")

        printed_by = request.user.get_full_name() or request.user.username
        try:
            pdf_bytes, doc_meta = render_provisional_results_pdf(
                student,
                show_scores=show_scores,
                printed_by=printed_by,
                request=request,
            )
        except Exception as exc:
            return Response(
                {"detail": f"PDF generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        safe_reg = (student.reg_no or str(student.pk)).replace("/", "-")
        prefix = doc_meta.get("filename_prefix", "Results")
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{prefix}_{safe_reg}.pdf"'
        return response


class BonafideExamCardPdfView(APIView):
    """Admin: download examination card / permit PDF for a bonafide student."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not _require_view_admitted(request.user):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        student = _get_bonafide_student(request, pk)
        if not student:
            return Response({"detail": "Student not found."}, status=status.HTTP_404_NOT_FOUND)
        assert_admitted_student_access(request.user, student)

        from examinations.services.exam_card import build_exam_card_payload
        from examinations.services.exam_card_pdf import render_exam_card_pdf

        payload = build_exam_card_payload(student, request=request, issue_token=True)
        if not payload.get("can_print"):
            blockers = payload.get("blockers") or []
            return Response(
                {
                    "detail": " ".join(blockers)
                    or "Cannot issue examination card for this student."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            pdf_bytes = render_exam_card_pdf(student, request=request)
        except Exception as exc:
            return Response(
                {"detail": f"PDF generation failed: {exc}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        reg = (student.reg_no or "student").replace("/", "-")
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="exam_card_{reg}.pdf"'
        return response
