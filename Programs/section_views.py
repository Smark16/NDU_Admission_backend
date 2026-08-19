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
    get_section_for_batch_or_raise,
    list_peer_batches_for_sharing,
    list_sections_for_batch,
    move_students_to_section,
    serialize_section,
    validate_linked_batches,
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


def _parse_linked_batch_ids(raw) -> list[int]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


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
                "peer_batches": list_peer_batches_for_sharing(batch.id),
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

        is_shared_raw = request.data.get("is_shared", False)
        if isinstance(is_shared_raw, bool):
            is_shared = is_shared_raw
        else:
            is_shared = str(is_shared_raw).lower() in ("1", "true", "yes", "on")

        linked_batch_ids = _parse_linked_batch_ids(
            request.data.get("linked_batch_ids")
        )

        if TeachingSection.objects.filter(program_batch=batch, code=code).exists():
            return Response(
                {"detail": f"Section code '{code}' already exists on this cohort."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        linked_batches = []
        if is_shared:
            try:
                linked_batches = validate_linked_batches(
                    owner_batch=batch, linked_batch_ids=linked_batch_ids
                )
            except ValueError as exc:
                return Response(
                    {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
                )
        elif linked_batch_ids:
            return Response(
                {
                    "detail": (
                        "linked_batch_ids can only be set when is_shared is true."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        section = TeachingSection.objects.create(
            program_batch=batch,
            code=code,
            name=name,
            is_default=False,
            is_shared=is_shared,
            max_capacity=max_capacity,
            is_active=True,
        )
        if linked_batches:
            section.linked_batches.set(linked_batches)

        return Response(
            serialize_section(section, student_count=0),
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

        update_links = "linked_batch_ids" in request.data or "is_shared" in request.data
        if update_links:
            if section.is_default:
                return Response(
                    {
                        "detail": (
                            "The default section cannot become a shared "
                            "cross-programme section."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            is_shared = section.is_shared
            if "is_shared" in request.data:
                raw = request.data.get("is_shared")
                if isinstance(raw, bool):
                    is_shared = raw
                else:
                    is_shared = str(raw).lower() in ("1", "true", "yes", "on")
            linked_batch_ids = _parse_linked_batch_ids(
                request.data.get(
                    "linked_batch_ids",
                    list(section.linked_batches.values_list("id", flat=True)),
                )
            )
            if is_shared:
                try:
                    linked_batches = validate_linked_batches(
                        owner_batch=section.program_batch,
                        linked_batch_ids=linked_batch_ids,
                    )
                except ValueError as exc:
                    return Response(
                        {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
                    )
                section.is_shared = True
                section.save()
                section.linked_batches.set(linked_batches)
            else:
                section.is_shared = False
                section.save()
                section.linked_batches.clear()
        else:
            section.save()

        # Prefer listing from the caller's batch context when provided.
        list_batch_id = section.program_batch_id
        try:
            ctx = int(request.query_params.get("batch_id") or 0)
            if ctx:
                list_batch_id = ctx
        except (TypeError, ValueError):
            pass
        sections = list_sections_for_batch(list_batch_id)
        payload = next((s for s in sections if s["id"] == section.id), None)
        return Response(payload or serialize_section(section))


class ListSectionStudentsView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def get(self, request, batch_id: int, section_id: int):
        batch = _get_batch_or_404(batch_id)
        if isinstance(batch, Response):
            return batch
        assert_program_in_user_faculties(request.user, batch.program)

        try:
            section = get_section_for_batch_or_raise(section_id, batch.pk)
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Shared sections: show all members; for local view of a shared section
        # from one batch, still show everyone so staff see the combined class.
        qs = (
            StudentProgrammeEnrollment.objects.filter(teaching_section=section)
            .select_related(
                "student__application",
                "program",
                "program_batch",
                "program_batch__program",
            )
            .order_by(
                "program_batch__program__name",
                "student__reg_no",
                "student__student_id",
            )
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
        for spe in qs:
            app = getattr(spe.student, "application", None)
            name = ""
            if app is not None:
                name = f"{app.first_name or ''} {app.last_name or ''}".strip()
            prog = getattr(spe, "program", None) or getattr(
                spe.program_batch, "program", None
            )
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
                    "program_batch_id": spe.program_batch_id,
                    "program_name": prog.name if prog else None,
                    "program_code": getattr(prog, "short_form", None) if prog else None,
                    "from_this_batch": spe.program_batch_id == batch.pk,
                }
            )

        return Response(
            {
                "section_id": section.id,
                "section_code": section.code,
                "section_name": section.name,
                "is_shared": bool(section.is_shared),
                "count": len(students),
                "students": students,
            }
        )


class MoveStudentsToSectionView(_BatchUnavailableMixin, APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def post(self, request, batch_id: int):
        from django.db.utils import ProgrammingError

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
        except ProgrammingError as exc:
            return Response(
                {
                    "detail": (
                        "Cannot move students: enrollment teaching_section column is missing. "
                        "On the server run: python manage.py ensure_teaching_section_columns "
                        "&& sudo systemctl restart gunicorn"
                    ),
                    "error": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception as exc:
            return Response(
                {"detail": str(exc) or "Could not move students to section."},
                status=status.HTTP_400_BAD_REQUEST,
            )

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
