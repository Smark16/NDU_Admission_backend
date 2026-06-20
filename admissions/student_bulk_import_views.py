from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.permissions import user_can_admit_applicant
from admissions.student_bulk_import import (
    build_student_import_template_csv,
    process_student_batch_import,
    STUDENT_IMPORT_OPTIONAL_HEADERS,
    STUDENT_IMPORT_REQUIRED_HEADERS,
)


class StudentBulkImportTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {"detail": "You do not have permission to import students."},
                status=status.HTTP_403_FORBIDDEN,
            )
        content = build_student_import_template_csv()
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="student_batch_import_template.csv"'
        return response


class StudentBulkImportView(APIView):
    """POST multipart: program_batch_id (academic cohort), campus_id, file.

    ``program_batch_id`` is the academic ``Programs.ProgramBatch``. Admission intake is resolved
    automatically from the active intake unless ``admission_batch_id`` is supplied.

    SchoolPay registration is on by default (register_schoolpay=true).

    Optional CSV columns for continuing students (same file as student details):
    current_year_of_study, current_term_number, fees_paid_ugx, fees_paid_reference,
    fees_outstanding_ugx, admission_fee_paid. Legacy-only fee import remains available at
    POST /api/admissions/students/fee_balance_import.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {"detail": "You do not have permission to import students."},
                status=status.HTTP_403_FORBIDDEN,
            )

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            program_batch_id = int(request.data.get("program_batch_id"))
            campus_id = int(request.data.get("campus_id"))
        except (TypeError, ValueError):
            return Response(
                {
                    "detail": "program_batch_id and campus_id are required integers.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw_admission_batch = request.data.get("admission_batch_id")
        admission_batch_id = None
        if raw_admission_batch not in (None, ""):
            try:
                admission_batch_id = int(raw_admission_batch)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "admission_batch_id must be an integer when provided."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        raw = str(request.data.get("register_schoolpay", "true")).lower()
        register_schoolpay = raw not in ("0", "false", "no", "off")

        raw_skip = str(request.data.get("skip_existing_reg_no", "false")).lower()
        skip_existing_reg_no = raw_skip in ("1", "true", "yes", "on")

        try:
            result = process_student_batch_import(
                uploaded_file=uploaded,
                program_batch_id=program_batch_id,
                admission_batch_id=admission_batch_id,
                campus_id=campus_id,
                admitted_by=request.user,
                register_schoolpay=register_schoolpay,
                skip_existing_reg_no=skip_existing_reg_no,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                **result,
                "required_columns": STUDENT_IMPORT_REQUIRED_HEADERS,
                "optional_columns": STUDENT_IMPORT_OPTIONAL_HEADERS,
            },
            status=status.HTTP_200_OK if result["failed"] == 0 else status.HTTP_207_MULTI_STATUS,
        )
