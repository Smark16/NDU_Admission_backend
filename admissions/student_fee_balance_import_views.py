from django.http import HttpResponse
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.permissions import user_can_admit_applicant
from admissions.student_fee_balance_import import (
    FEE_BALANCE_IMPORT_HEADERS,
    build_fee_balance_import_template_csv,
    process_fee_balance_import,
)


class StudentFeeBalanceImportTemplateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {"detail": "You do not have permission to import fee balances."},
                status=status.HTTP_403_FORBIDDEN,
            )
        content = build_fee_balance_import_template_csv()
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="student_fee_balance_import_template.csv"'
        return response


class StudentFeeBalanceImportView(APIView):
    """POST multipart file — legacy fee balances for existing admitted students."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if not user_can_admit_applicant(request.user):
            return Response(
                {"detail": "You do not have permission to import fee balances."},
                status=status.HTTP_403_FORBIDDEN,
            )

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response({"detail": "file is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = process_fee_balance_import(
                uploaded_file=uploaded,
                imported_by=request.user,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {**result, "columns": FEE_BALANCE_IMPORT_HEADERS},
            status=status.HTTP_200_OK if result["failed"] == 0 else status.HTTP_207_MULTI_STATUS,
        )
