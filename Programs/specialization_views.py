"""
Programme Specialization API
------------------------------
Manages the authoritative list of specialization track names for a programme.

Endpoints (all require IsAuthenticated staff unless noted):

  GET    program/<id>/specializations          — list all tracks for a programme
  POST   program/<id>/specializations          — add a new track
  PATCH  program/specialization/<pk>           — rename / toggle active
  DELETE program/specialization/<pk>           — remove a track

These are admin-facing operations.  The student-facing specialization choice
lives in enrollment_views.py (my_enrollment/select_specialization).
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Program, ProgramSpecialization
from .serializers import ProgramSpecializationSerializer


class ProgramSpecializationListCreateView(APIView):
    """List or add specialization tracks for a programme."""
    permission_classes = [IsAuthenticated]

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


class ProgramSpecializationDetailView(APIView):
    """Rename, toggle, or delete a single specialization track."""
    permission_classes = [IsAuthenticated]

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
