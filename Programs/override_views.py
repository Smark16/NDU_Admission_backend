"""
Staff-facing API for StudentCurriculumOverride management.

Endpoints:
  GET    admin/student/<student_id>/curriculum        — full curriculum with override status
  GET    admin/enrollment/<enrollment_id>/overrides   — list overrides for an enrollment
  POST   admin/enrollment/<enrollment_id>/overrides   — create an override
  GET    admin/override/<pk>                          — retrieve one override
  PATCH  admin/override/<pk>                          — update an override
  DELETE admin/override/<pk>                          — remove an override
"""
from django.shortcuts import get_object_or_404
from rest_framework import status
from .permissions import CurriculumOverrideAPIPermission
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AdmittedStudent
from .curriculum_inheritance import curriculum_owner_program
from .models import (
    ProgramCurriculumLine,
    StudentCurriculumOverride,
    StudentProgrammeEnrollment,
    resolve_program_default_curriculum_version,
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _override_to_dict(o: StudentCurriculumOverride) -> dict:
    return {
        "id":                      o.id,
        "curriculum_line_id":      o.curriculum_line_id,
        "course_code":             o.curriculum_line.catalog_course.code,
        "course_title":            o.curriculum_line.catalog_course.title,
        "blueprint_year":          o.curriculum_line.year_of_study,
        "blueprint_term":          o.curriculum_line.term_number,
        "override_type":           o.override_type,
        "override_type_display":   o.get_override_type_display(),
        "effective_year_of_study": o.effective_year_of_study,
        "effective_term_number":   o.effective_term_number,
        "transferred_grade":       o.transferred_grade,
        "transferred_institution": o.transferred_institution,
        "substituted_by_id":       o.substituted_by_id,
        "substituted_by_code":     o.substituted_by.catalog_course.code if o.substituted_by_id else None,
        "notes":                   o.notes,
        "decided_by":              o.decided_by.get_full_name() if o.decided_by else None,
        "decided_at":              o.decided_at.isoformat() if o.decided_at else None,
    }


def _line_to_dict(line: ProgramCurriculumLine, override: StudentCurriculumOverride | None) -> dict:
    return {
        "curriculum_line_id": line.id,
        "course_code":        line.catalog_course.code,
        "course_title":       line.catalog_course.title,
        "credit_units":       str(line.catalog_course.credit_units),
        "course_type":        line.course_type,
        "year_of_study":      line.year_of_study,
        "term_number":        line.term_number,
        "sort_order":         line.sort_order,
        "override": _override_to_dict(override) if override else None,
        "path_status": override.override_type if override else "standard",
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class StudentCurriculumView(APIView):
    """Full curriculum blueprint for a student, annotated with any overrides.

    URL: GET /api/program/admin/student/<student_id>/curriculum
    """
    permission_classes = [CurriculumOverrideAPIPermission]

    def get(self, request, student_id):
        student = get_object_or_404(AdmittedStudent, pk=student_id)

        try:
            enrollment = StudentProgrammeEnrollment.objects.select_related(
                "program", "program_batch", "curriculum_version"
            ).get(student=student)
        except StudentProgrammeEnrollment.DoesNotExist:
            return Response(
                {"detail": "No academic enrollment found for this student."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if enrollment.curriculum_version_id is None:
            fallback = (
                enrollment.program_batch.curriculum_version
                if enrollment.program_batch_id and enrollment.program_batch.curriculum_version_id
                else resolve_program_default_curriculum_version(enrollment.program)
            )
            if fallback:
                enrollment.curriculum_version = fallback
                enrollment.save(update_fields=["curriculum_version", "updated_at"])

        lines = (
            ProgramCurriculumLine.objects
            .filter(
                program=curriculum_owner_program(enrollment.program),
                curriculum_version=enrollment.curriculum_version,
                is_active=True,
            )
            .select_related("catalog_course")
            .order_by("year_of_study", "term_number", "sort_order")
        )

        overrides_map = {
            o.curriculum_line_id: o
            for o in StudentCurriculumOverride.objects.filter(
                enrollment=enrollment
            ).select_related("curriculum_line__catalog_course", "substituted_by__catalog_course", "decided_by")
        }

        result = [_line_to_dict(line, overrides_map.get(line.id)) for line in lines]

        return Response({
            "student_id":           student.student_id,
            "reg_no":               student.reg_no,
            "student_name":         student.full_name,
            "enrollment_id":        enrollment.id,
            "program":              enrollment.program.name,
            "entry_year":           enrollment.entry_year_of_study,
            "entry_term":           enrollment.entry_term_number,
            "current_year":         enrollment.current_year_of_study,
            "current_term":         enrollment.current_term_number,
            "enrollment_status":    enrollment.status,
            "curriculum":           result,
            "total_lines":          len(result),
            "override_count":       len(overrides_map),
            "standard_count":       len(result) - len(overrides_map),
        })


class EnrollmentOverrideListCreate(APIView):
    """List and create overrides for a specific enrollment.

    URL: GET/POST /api/program/admin/enrollment/<enrollment_id>/overrides
    """
    permission_classes = [CurriculumOverrideAPIPermission]

    def get(self, request, enrollment_id):
        enrollment = get_object_or_404(StudentProgrammeEnrollment, pk=enrollment_id)
        overrides = StudentCurriculumOverride.objects.filter(
            enrollment=enrollment
        ).select_related(
            "curriculum_line__catalog_course",
            "substituted_by__catalog_course",
            "decided_by",
        ).order_by(
            "curriculum_line__year_of_study",
            "curriculum_line__term_number",
        )
        return Response([_override_to_dict(o) for o in overrides])

    def post(self, request, enrollment_id):
        enrollment = get_object_or_404(StudentProgrammeEnrollment, pk=enrollment_id)

        curriculum_line_id = request.data.get("curriculum_line_id")
        override_type      = request.data.get("override_type", "").strip()

        if not curriculum_line_id:
            return Response(
                {"detail": "curriculum_line_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not override_type:
            return Response(
                {"detail": "override_type is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        valid_types = [c[0] for c in StudentCurriculumOverride.OVERRIDE_TYPE_CHOICES]
        if override_type not in valid_types:
            return Response(
                {"detail": f"Invalid override_type. Choices: {valid_types}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        line = get_object_or_404(
            ProgramCurriculumLine,
            pk=curriculum_line_id,
            program=enrollment.program,
            curriculum_version=enrollment.curriculum_version,
        )

        # Validate position fields for deferred/backlog
        eff_year = request.data.get("effective_year_of_study")
        eff_term = request.data.get("effective_term_number")
        if override_type in ("deferred", "backlog"):
            if not eff_year or not eff_term:
                return Response(
                    {"detail": "effective_year_of_study and effective_term_number are required for deferred/backlog."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Prevent duplicate
        if StudentCurriculumOverride.objects.filter(
            enrollment=enrollment, curriculum_line=line
        ).exists():
            return Response(
                {"detail": "An override already exists for this curriculum line. Use PATCH to update it."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        substituted_by = None
        sub_id = request.data.get("substituted_by_id")
        if override_type == "substituted":
            if not sub_id:
                return Response(
                    {"detail": "substituted_by_id is required for substituted type."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            substituted_by = get_object_or_404(
                ProgramCurriculumLine,
                pk=sub_id,
                program=enrollment.program,
                curriculum_version=enrollment.curriculum_version,
            )

        override = StudentCurriculumOverride.objects.create(
            enrollment=enrollment,
            curriculum_line=line,
            override_type=override_type,
            effective_year_of_study=eff_year or None,
            effective_term_number=eff_term or None,
            transferred_grade=request.data.get("transferred_grade", ""),
            transferred_institution=request.data.get("transferred_institution", ""),
            substituted_by=substituted_by,
            notes=request.data.get("notes", ""),
            decided_by=request.user,
        )

        return Response(_override_to_dict(override), status=status.HTTP_201_CREATED)


class OverrideDetailView(APIView):
    """Retrieve, update, or delete a single override.

    URL: GET/PATCH/DELETE /api/program/admin/override/<pk>
    """
    permission_classes = [CurriculumOverrideAPIPermission]

    def _get(self, pk):
        return get_object_or_404(
            StudentCurriculumOverride.objects.select_related(
                "curriculum_line__catalog_course",
                "substituted_by__catalog_course",
                "decided_by",
            ),
            pk=pk,
        )

    def get(self, request, pk):
        return Response(_override_to_dict(self._get(pk)))

    def patch(self, request, pk):
        override = self._get(pk)

        override_type = request.data.get("override_type", override.override_type)
        valid_types = [c[0] for c in StudentCurriculumOverride.OVERRIDE_TYPE_CHOICES]
        if override_type not in valid_types:
            return Response(
                {"detail": f"Invalid override_type. Choices: {valid_types}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        eff_year = request.data.get("effective_year_of_study", override.effective_year_of_study)
        eff_term = request.data.get("effective_term_number", override.effective_term_number)

        if override_type in ("deferred", "backlog") and (not eff_year or not eff_term):
            return Response(
                {"detail": "effective_year_of_study and effective_term_number are required for deferred/backlog."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        override.override_type           = override_type
        override.effective_year_of_study = eff_year
        override.effective_term_number   = eff_term
        override.transferred_grade       = request.data.get("transferred_grade",       override.transferred_grade)
        override.transferred_institution = request.data.get("transferred_institution", override.transferred_institution)
        override.notes                   = request.data.get("notes",                   override.notes)
        override.decided_by              = request.user
        override.save()

        return Response(_override_to_dict(override))

    def delete(self, request, pk):
        override = self._get(pk)
        code = override.curriculum_line.catalog_course.code
        override.delete()
        return Response(
            {"detail": f"Override for {code} removed. Student is now on the standard path for this course."},
            status=status.HTTP_204_NO_CONTENT,
        )
