"""
Programme Specialization API
------------------------------
Manages the authoritative list of specialization track names for a programme.

Endpoints (all require IsAuthenticated staff unless noted):

  GET    program/<id>/specializations                        — list all tracks for a programme
  POST   program/<id>/specializations                        — add a new track
  GET    program/<id>/specializations/bulk_import_template   — download CSV template
  POST   program/<id>/specializations/bulk_upload            — import many tracks from CSV
  PATCH  program/specialization/<pk>                         — rename / toggle active
  DELETE program/specialization/<pk>                           — remove a track

These are admin-facing operations.  The student-facing specialization choice
lives in enrollment_views.py (my_enrollment/select_specialization).
"""
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from .permissions import ProgramSchedulingAPIPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Program, ProgramSpecialization
from .serializers import ProgramSpecializationSerializer
from .specialization_bulk_import import (
    build_specialization_import_template_csv,
    process_specialization_bulk_import,
)


class ProgramSpecializationListCreateView(APIView):
    """List or add specialization tracks for a programme."""
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        qs = ProgramSpecialization.objects.filter(program=program)
        # Optional: ?active_only=true
        if request.query_params.get('active_only', 'false').lower() == 'true':
            qs = qs.filter(is_active=True)
        serializer = ProgramSpecializationSerializer(qs, many=True)
        return Response({
            'program_id': program.id,
            'program_name': program.name,
            'has_specialization': program.has_specialization,
            'specialization_entry_year': program.specialization_entry_year,
            'specialization_entry_term': program.specialization_entry_term,
            'count': qs.count(),
            'specializations': serializer.data,
        })

    def post(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        data = {**request.data, 'program': program.id}
        serializer = ProgramSpecializationSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProgramSpecializationBulkImportTemplateView(APIView):
    """Download CSV template for bulk specialization import."""

    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)
        content = build_specialization_import_template_csv()
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        slug = (program.short_form or program.code or f"program_{program.id}").replace(" ", "_")
        response["Content-Disposition"] = (
            f'attachment; filename="{slug}_specializations_template.csv"'
        )
        return response


class ProgramSpecializationBulkUploadView(APIView):
    """
    POST /api/program/program/<program_id>/specializations/bulk_upload

    Multipart field:
      - file (required CSV)

    CSV columns:
      name*       — teaching combination / track name (required)
      is_active   — true/false (optional, default true)
    """

    permission_classes = [ProgramSchedulingAPIPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, program_id):
        program = get_object_or_404(Program, pk=program_id)

        uploaded = request.FILES.get("file")
        if not uploaded:
            return Response(
                {"detail": 'No file received. Send the CSV as multipart field "file".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not (uploaded.name or "").lower().endswith(".csv"):
            return Response(
                {"detail": "Only .csv files are accepted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return Response(
                {"detail": "Could not decode file — ensure it is UTF-8 encoded."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = process_specialization_bulk_import(program, text)
        if not result.get("ok"):
            return Response(
                {"detail": result.get("detail", "Import failed.")},
                status=status.HTTP_400_BAD_REQUEST,
            )

        qs = ProgramSpecialization.objects.filter(program=program).order_by("name")
        serializer = ProgramSpecializationSerializer(qs, many=True)
        return Response(
            {
                **result,
                "specializations": serializer.data,
                "count": qs.count(),
            },
            status=status.HTTP_200_OK,
        )


class ProgramSpecializationDetailView(APIView):
    """Rename, toggle, or delete a single specialization track."""
    permission_classes = [ProgramSchedulingAPIPermission]

    def _get(self, pk):
        return get_object_or_404(ProgramSpecialization, pk=pk)

    def get(self, request, pk):
        return Response(ProgramSpecializationSerializer(self._get(pk)).data)

    def patch(self, request, pk):
        spec = self._get(pk)
        allowed = {'name', 'is_active'}
        data = {k: v for k, v in request.data.items() if k in allowed}
        # Keep program immutable
        data['program'] = spec.program_id
        serializer = ProgramSpecializationSerializer(spec, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        spec = self._get(pk)
        name = spec.name
        program_name = spec.program.short_form
        spec.delete()
        return Response(
            {'detail': f"Specialization '{name}' removed from {program_name}."},
            status=status.HTTP_204_NO_CONTENT,
        )
