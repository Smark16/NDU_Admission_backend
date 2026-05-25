from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent

from .models import ExamCardToken
from .services.exam_card import (
    build_exam_card_payload,
    build_exam_card_verify_payload,
)
from .services.exam_card_pdf import render_exam_card_pdf
from .views import _student_for_user


class StudentExamCardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        student = _student_for_user(request.user)
        if not student:
            return Response({"detail": "Student record not found."}, status=404)

        if request.query_params.get("format") == "pdf":
            payload = build_exam_card_payload(student, request=request, issue_token=True)
            if not payload["can_print"]:
                return Response(
                    {"detail": " ".join(payload["blockers"]) or "Cannot issue examination card."},
                    status=400,
                )
            pdf_bytes = render_exam_card_pdf(student, request=request)
            reg = (student.reg_no or "student").replace("/", "-")
            filename = f"exam_card_{reg}.pdf"
            response = HttpResponse(pdf_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'inline; filename="{filename}"'
            return response

        return Response(build_exam_card_payload(student, request=request, issue_token=True))


class ExamCardVerifyView(APIView):
    """Public QR verification — live payment status (accounts at block entrance)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, verification_code):
        token = (
            ExamCardToken.objects.select_related(
                "student",
                "student__application",
                "student__admitted_program",
            )
            .filter(verification_code=verification_code)
            .first()
        )
        if not token:
            return Response({"valid": False, "detail": "Examination card not found."}, status=404)
        return Response(build_exam_card_verify_payload(token, request=request))
