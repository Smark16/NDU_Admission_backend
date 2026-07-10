from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import FinanceModuleAdminPermission
from admissions.models import AdmittedStudent

from .registration_lookup import (
    build_registration_lookup_payload,
    search_admitted_students,
    student_summary_row,
)


class AdminRegistrationLookupSearchView(APIView):
    """
    GET /api/payments/admin/registration_lookup?q=...
    Search by paycode, reg no, name, email, or internal student pk.
  """

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request):
        q = (request.query_params.get("q") or "").strip()
        if not q:
            return Response(
                {"detail": "Enter a reg number, paycode, name, or email to search."},
                status=400,
            )

        matches = list(search_admitted_students(q))
        if not matches:
            return Response(
                {"matches": [], "detail": None, "message": "No admitted student found."},
                status=404,
            )

        summaries = [student_summary_row(s) for s in matches]

        if len(matches) == 1:
            return Response(
                {
                    "matches": summaries,
                    "detail": build_registration_lookup_payload(matches[0], request),
                }
            )

        return Response({"matches": summaries, "detail": None})


class AdminRegistrationLookupDetailView(APIView):
    """GET /api/payments/admin/registration_lookup/<admitted_student_id>"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request, student_id: int):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related(
                "admitted_program",
                "admitted_campus",
                "application",
            ),
            pk=student_id,
            is_admitted=True,
        )
        return Response(build_registration_lookup_payload(student, request))
