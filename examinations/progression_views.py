"""Student and cohort progression standings."""
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import (
    assert_admitted_student_access,
    assert_program_batch_access,
    assert_program_in_user_faculties,
)
from admissions.models import AdmittedStudent
from Programs.models import Program, ProgramBatch, Semester

from .permissions import CanViewAllResults
from .services.progression import compute_student_progression, progression_for_scope


def _int_param(request, name):
    raw = (request.query_params.get(name) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class StudentProgressionView(APIView):
    permission_classes = [IsAuthenticated, CanViewAllResults]

    def get(self, request, student_id):
        student = get_object_or_404(
            AdmittedStudent.objects.select_related("application", "admitted_program"),
            pk=student_id,
            is_admitted=True,
        )
        assert_admitted_student_access(request.user, student)
        return Response(compute_student_progression(student))


class ProgressionReportView(APIView):
    permission_classes = [IsAuthenticated, CanViewAllResults]

    def get(self, request):
        program_id = _int_param(request, "program_id")
        program_batch_id = _int_param(request, "program_batch_id")
        semester_id = _int_param(request, "semester_id")
        if not program_id and not program_batch_id and not semester_id:
            return Response(
                {"detail": "Select a programme, batch, or semester."},
                status=400,
            )
        if program_id:
            program = get_object_or_404(Program, pk=program_id)
            assert_program_in_user_faculties(request.user, program)
        if program_batch_id:
            batch = get_object_or_404(
                ProgramBatch.objects.select_related("program"),
                pk=program_batch_id,
            )
            assert_program_batch_access(request.user, batch)
        if semester_id:
            semester = get_object_or_404(
                Semester.objects.select_related("program_batch", "program_batch__program"),
                pk=semester_id,
            )
            assert_program_batch_access(request.user, semester.program_batch)
        rows = progression_for_scope(
            user=request.user,
            program_id=program_id,
            program_batch_id=program_batch_id,
            semester_id=semester_id,
        )
        return Response({"count": len(rows), "students": rows})
