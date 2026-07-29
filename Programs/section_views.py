"""API views for teaching sections within a ProgramBatch cohort."""
from __future__ import annotations

from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import (
    assert_can_modify_program_batch_structure,
    assert_program_in_user_faculties,
)

from .models import ProgramBatch, StudentProgrammeEnrollment, TeachingSection
from .permissions import ProgramSchedulingAPIPermission
from .teaching_sections import (
    DEFAULT_MAX_CAPACITY,
    list_sections_for_batch,
    move_students_to_section,
)


class _BatchUnavailableMixin:
    def dispatch(self, request, *args, **kwargs):
        from django.db.utils import ProgrammingError

        try:
            return super().dispatch(request, *args, **kwargs)
        except ProgrammingError:
            return Response(
                {"detail": "Teaching sections are not available on this server."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


def _get_batch_or_404(batch_id: int) -> ProgramBatch | Response:
    try:
        return ProgramBatch.objects.select_related("program").get(pk=batch_id)
    except ProgramBatch.DoesNotExist:
        return Response(
            {"detail": "Academic programme batch not found."},
            status=status.HTTP_404_NOT_FOUND,
        )


class ListTeachingSectionsView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, batch_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_program_in_user_faculties(request.user, batch.program)
        return Response(
            {
                "program_batch_id": batch.id,
                "program_batch_name": batch.name,
                "sections": list_sections_for_batch(batch.id),
            }
        )


class CreateTeachingSectionView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def post(self, request, batch_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_can_modify_program_batch_structure(request.user, batch)

        code = (request.data.get("code") or "").strip().upper()
        name = (request.data.get("name") or "").strip()
        if not code:
            return Response(
                {"detail": "code is required (e.g. B, C, AFT)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not name:
            name = f"Section {code}"

        try:
            max_capacity = int(
                request.data.get("max_capacity", DEFAULT_MAX_CAPACITY)
            )
        except (TypeError, ValueError):
            return Response(
                {"detail": "max_capacity must be an integer."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if max_capacity < 0:
            return Response(
                {"detail": "max_capacity cannot be negative."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if TeachingSection.objects.filter(program_batch=batch, code=code).exists():
            return Response(
                {"detail": f"Section code '{code}' already exists on this cohort."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        section = TeachingSection.objects.create(
            program_batch=batch,
            code=code,
            name=name,
            is_default=False,
            max_capacity=max_capacity,
            is_active=True,
        )
        return Response(
            {
                "id": section.id,
                "program_batch_id": batch.id,
                "code": section.code,
                "name": section.name,
                "is_default": section.is_default,
                "max_capacity": section.max_capacity,
                "is_active": section.is_active,
                "student_count": 0,
            },
            status=status.HTTP_201_CREATED,
        )


class UpdateTeachingSectionView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def patch(self, request, section_id: int):
        try:
            section = TeachingSection.objects.select_related(
                "program_batch__program"
            ).get(pk=section_id)
        except TeachingSection.DoesNotExist:
            return Response(
                {"detail": "Teaching section not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        assert_can_modify_program_batch_structure(
            request.user, section.program_batch
        )

        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response(
                    {"detail": "name cannot be empty."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            section.name = name

        if "max_capacity" in request.data:
            try:
                max_capacity = int(request.data.get("max_capacity"))
            except (TypeError, ValueError):
                return Response(
                    {"detail": "max_capacity must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if max_capacity < 0:
                return Response(
                    {"detail": "max_capacity cannot be negative."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            section.max_capacity = max_capacity

        if "is_active" in request.data:
            raw = request.data.get("is_active")
            if isinstance(raw, bool):
                section.is_active = raw
            else:
                section.is_active = str(raw).lower() in ("1", "true", "yes", "on")
            if not section.is_active and section.is_default:
                return Response(
                    {"detail": "The default section cannot be deactivated."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Do not allow flipping is_default via this endpoint (protect uniqueness).
        section.save()
        sections = list_sections_for_batch(section.program_batch_id)
        payload = next((s for s in sections if s["id"] == section.id), None)
        return Response(payload or {"id": section.id})


class ListSectionStudentsView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, batch_id: int, section_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_program_in_user_faculties(request.user, batch.program)

        try:
            section = TeachingSection.objects.get(
                pk=section_id, program_batch_id=batch.pk
            )
        except TeachingSection.DoesNotExist:
            return Response(
                {"detail": "Teaching section not found on this cohort."},
                status=status.HTTP_404_NOT_FOUND,
            )

        qs = (
            StudentProgrammeEnrollment.objects.filter(teaching_section=section)
            .select_related("student__application", "program", "program_batch")
            .order_by("student__reg_no", "student__student_id")
        )
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(student__reg_no__icontains=search)
                | Q(student__student_id__icontains=search)
                | Q(student__application__first_name__icontains=search)
                | Q(student__application__last_name__icontains=search)
            )

        students = []
        for spe in qs[:500]:
            app = getattr(spe.student, "application", None)
            name = ""
            if app is not None:
                name = f"{app.first_name or ''} {app.last_name or ''}".strip()
            students.append(
                {
                    "enrollment_id": spe.id,
                    "student_id": spe.student_id,
                    "admitted_student_id": spe.student_id,
                    "reg_no": spe.student.reg_no,
                    "schoolpay_code": spe.student.student_id,
                    "name": name or spe.student.full_name,
                    "status": spe.status,
                    "current_year_of_study": spe.current_year_of_study,
                    "current_term_number": spe.current_term_number,
                }
            )

        return Response(
            {
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "count": len(students),
                "students": students,
            }
        )


class MoveStudentsToSectionView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def post(self, request, batch_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_can_modify_program_batch_structure(request.user, batch)

        try:
            target_section_id = int(request.data.get("target_section_id"))
        except (TypeError, ValueError):
            return Response(
                {"detail": "target_section_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollment_ids = request.data.get("enrollment_ids") or []
        student_ids = request.data.get("student_ids") or []
        if not isinstance(enrollment_ids, list):
            enrollment_ids = []
        if not isinstance(student_ids, list):
            student_ids = []

        enrollment_ids = [int(x) for x in enrollment_ids if str(x).isdigit() or isinstance(x, int)]
        student_ids = [int(x) for x in student_ids if str(x).isdigit() or isinstance(x, int)]

        enforce_raw = request.data.get("enforce_capacity", True)
        if isinstance(enforce_raw, bool):
            enforce_capacity = enforce_raw
        else:
            enforce_capacity = str(enforce_raw).lower() not in ("0", "false", "no", "off")

        try:
            result = move_students_to_section(
                program_batch_id=batch.id,
                target_section_id=target_section_id,
                enrollment_ids=enrollment_ids or None,
                student_ids=student_ids or None,
                enforce_capacity=enforce_capacity,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class ListBatchUnsectionedStudentsView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, batch_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_program_in_user_faculties(request.user, batch.program)

        qs = (
            StudentProgrammeEnrollment.objects.filter(
                program_batch_id=batch.pk, teaching_section__isnull=True
            )
            .select_related("student__application")
            .order_by("student__reg_no")
        )
        students = []
        for spe in qs[:500]:
            app = getattr(spe.student, "application", None)
            name = ""
            if app is not None:
                name = f"{app.first_name or ''} {app.last_name or ''}".strip()
            students.append(
                {
                    "enrollment_id": spe.id,
                    "student_id": spe.student_id,
                    "reg_no": spe.student.reg_no,
                    "name": name or spe.student.full_name,
                    "status": spe.status,
                }
            )
        return Response({"count": len(students), "students": students})
