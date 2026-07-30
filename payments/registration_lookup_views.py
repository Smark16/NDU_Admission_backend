import logging

from django.db.utils import ProgrammingError
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

logger = logging.getLogger(__name__)

MIGRATE_HINT = (
    "Database schema is behind application code for course enrollments. "
    "On the server run: python manage.py migrate Programs && sudo systemctl restart gunicorn"
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

        try:
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
        except ProgrammingError:
            logger.exception("registration_lookup search ProgrammingError")
            return Response({"detail": MIGRATE_HINT}, status=503)
        except Exception as exc:
            logger.exception("registration_lookup search failed")
            return Response({"detail": str(exc) or "Lookup failed."}, status=500)


class AdminRegistrationLookupDetailView(APIView):
    """GET /api/payments/admin/registration_lookup/<admitted_student_id>"""

    permission_classes = [FinanceModuleAdminPermission]

    def get(self, request, student_id: int):
        try:
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
        except ProgrammingError:
            logger.exception(
                "registration_lookup detail ProgrammingError student_id=%s", student_id
            )
            return Response({"detail": MIGRATE_HINT}, status=503)
        except Exception as exc:
            logger.exception("registration_lookup detail failed student_id=%s", student_id)
            return Response({"detail": str(exc) or "Could not load registration details."}, status=500)
