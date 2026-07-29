"""Teaching sections within an academic cohort (ProgramBatch)."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Count, F, Q

logger = logging.getLogger(__name__)

DEFAULT_SECTION_CODE = "MAIN"
DEFAULT_SECTION_NAME = "Main"
DEFAULT_MAX_CAPACITY = 120


def resolve_program_batch_for_course_unit(course_unit):
    """Return ProgramBatch for a course unit (direct FK or via semester)."""
    from Programs.models import ProgramBatch, Semester

    if course_unit is None:
        return None
    if getattr(course_unit, "program_batch_id", None):
        batch = getattr(course_unit, "program_batch", None)
        if batch is not None and getattr(batch, "pk", None):
            return batch
        return ProgramBatch.objects.filter(pk=course_unit.program_batch_id).first()

    semester = getattr(course_unit, "semester", None)
    if semester is None and getattr(course_unit, "semester_id", None):
        semester = (
            Semester.objects.select_related("program_batch")
            .filter(pk=course_unit.semester_id)
            .first()
        )
    if semester is not None:
        if getattr(semester, "program_batch_id", None):
            batch = getattr(semester, "program_batch", None)
            if batch is not None and getattr(batch, "pk", None):
                return batch
            return ProgramBatch.objects.filter(pk=semester.program_batch_id).first()
    return None


def ensure_default_teaching_section(program_batch, *, max_capacity: int = DEFAULT_MAX_CAPACITY):
    """
    Ensure the cohort has exactly one default teaching section.
    Creates MAIN / Main when missing.
    """
    from Programs.models import TeachingSection

    if program_batch is None or not getattr(program_batch, "pk", None):
        return None

    existing = (
        TeachingSection.objects.filter(program_batch_id=program_batch.pk, is_default=True)
        .order_by("id")
        .first()
    )
    if existing is not None:
        return existing

    section, created = TeachingSection.objects.get_or_create(
        program_batch_id=program_batch.pk,
        code=DEFAULT_SECTION_CODE,
        defaults={
            "name": DEFAULT_SECTION_NAME,
            "is_default": True,
            "max_capacity": max_capacity,
            "is_active": True,
        },
    )
    if not section.is_default:
        if not TeachingSection.objects.filter(
            program_batch_id=program_batch.pk, is_default=True
        ).exists():
            section.is_default = True
            section.save(update_fields=["is_default", "updated_at"])
    if created:
        logger.info(
            "Created default teaching section %s for ProgramBatch %s",
            section.code,
            program_batch.pk,
        )
    return section


def ensure_enrollment_teaching_section(enrollment, *, assign_only: bool = False):
    """
    Assign enrollment.teaching_section to the cohort default when missing or
    when the current section belongs to a different cohort.

    When assign_only=True, only mutates the in-memory instance (for use inside save()).
    """
    from Programs.models import TeachingSection

    if enrollment is None or not enrollment.program_batch_id:
        return enrollment

    needs = False
    if not enrollment.teaching_section_id:
        needs = True
    else:
        section_batch_id = None
        # Prefer cached related object when loaded
        section = getattr(enrollment, "teaching_section", None)
        if section is not None and getattr(section, "pk", None):
            section_batch_id = section.program_batch_id
        else:
            section_batch_id = (
                TeachingSection.objects.filter(pk=enrollment.teaching_section_id)
                .values_list("program_batch_id", flat=True)
                .first()
            )
        if section_batch_id != enrollment.program_batch_id:
            needs = True

    if not needs:
        return enrollment

    # Resolve batch without requiring select_related
    batch = getattr(enrollment, "program_batch", None)
    if batch is None or getattr(batch, "pk", None) != enrollment.program_batch_id:
        from Programs.models import ProgramBatch

        batch = ProgramBatch.objects.filter(pk=enrollment.program_batch_id).first()

    default = ensure_default_teaching_section(batch)
    if default is None:
        return enrollment

    enrollment.teaching_section = default
    if not assign_only and enrollment.pk:
        enrollment.save(update_fields=["teaching_section", "updated_at"])
    return enrollment


def section_headcount(section) -> int:
    from Programs.models import StudentProgrammeEnrollment

    return StudentProgrammeEnrollment.objects.filter(teaching_section_id=section.pk).count()


def list_sections_for_batch(program_batch_id: int) -> list[dict]:
    from Programs.models import ProgramBatch, TeachingSection

    batch = ProgramBatch.objects.filter(pk=program_batch_id).first()
    if batch is None:
        return []
    ensure_default_teaching_section(batch)

    qs = (
        TeachingSection.objects.filter(program_batch_id=program_batch_id)
        .annotate(student_count=Count("student_enrollments"))
        .order_by("-is_default", "code", "name")
    )
    return [
        {
            "id": s.id,
            "program_batch_id": s.program_batch_id,
            "code": s.code,
            "name": s.name,
            "is_default": s.is_default,
            "max_capacity": s.max_capacity,
            "is_active": s.is_active,
            "student_count": s.student_count,
            "at_or_over_capacity": (
                s.max_capacity > 0 and s.student_count >= s.max_capacity
            ),
        }
        for s in qs
    ]


@transaction.atomic
def move_students_to_section(
    *,
    program_batch_id: int,
    target_section_id: int,
    enrollment_ids: list[int] | None = None,
    student_ids: list[int] | None = None,
    enforce_capacity: bool = True,
) -> dict:
    """
    Move programme enrollments into a teaching section on the same cohort.
    ``student_ids`` are AdmittedStudent PKs; ``enrollment_ids`` are SPE PKs.
    """
    from Programs.models import ProgramBatch, StudentProgrammeEnrollment, TeachingSection

    try:
        batch = ProgramBatch.objects.get(pk=program_batch_id)
    except ProgramBatch.DoesNotExist as exc:
        raise ValueError("Academic programme batch not found.") from exc

    try:
        target = TeachingSection.objects.select_for_update().get(
            pk=target_section_id, program_batch_id=batch.pk
        )
    except TeachingSection.DoesNotExist as exc:
        raise ValueError("Target teaching section not found on this cohort.") from exc

    if not target.is_active:
        raise ValueError("Target teaching section is inactive.")

    qs = StudentProgrammeEnrollment.objects.select_for_update().filter(
        program_batch_id=batch.pk
    )
    if enrollment_ids:
        qs = qs.filter(pk__in=enrollment_ids)
    elif student_ids:
        qs = qs.filter(student_id__in=student_ids)
    else:
        raise ValueError("Provide enrollment_ids or student_ids to move.")

    enrollments = list(qs.select_related("student", "teaching_section"))
    if not enrollments:
        raise ValueError("No matching students found on this cohort.")

    already = [e for e in enrollments if e.teaching_section_id == target.pk]
    to_move = [e for e in enrollments if e.teaching_section_id != target.pk]

    if enforce_capacity and target.max_capacity > 0 and to_move:
        current = section_headcount(target)
        projected = current + len(to_move)
        if projected > target.max_capacity:
            raise ValueError(
                f"Moving {len(to_move)} student(s) would exceed capacity "
                f"({current}/{target.max_capacity} → {projected})."
            )

    moved = 0
    for enrollment in to_move:
        enrollment.teaching_section = target
        # Bypass SPE.save section auto-logic by setting FK then saving fields
        StudentProgrammeEnrollment.objects.filter(pk=enrollment.pk).update(
            teaching_section_id=target.pk
        )
        moved += 1

    return {
        "moved": moved,
        "already_in_section": len(already),
        "target_section_id": target.id,
        "target_section_code": target.code,
        "target_student_count": section_headcount(target),
    }


def backfill_all_teaching_sections(*, dry_run: bool = False) -> dict:
    """Create missing default sections and assign null/mismatched SPE rows."""
    from Programs.models import ProgramBatch, StudentProgrammeEnrollment, TeachingSection

    batches = list(ProgramBatch.objects.all().only("id"))
    created_defaults = 0
    assigned = 0

    if dry_run:
        missing_defaults = 0
        for batch in batches:
            if not TeachingSection.objects.filter(
                program_batch_id=batch.pk, is_default=True
            ).exists():
                missing_defaults += 1
        needing = StudentProgrammeEnrollment.objects.filter(
            Q(teaching_section__isnull=True)
            | ~Q(teaching_section__program_batch_id=F("program_batch_id"))
        ).count()
        return {
            "dry_run": True,
            "batches": len(batches),
            "defaults_to_create": missing_defaults,
            "enrollments_needing_assign": needing,
        }

    for batch in batches:
        before = TeachingSection.objects.filter(
            program_batch_id=batch.pk, is_default=True
        ).exists()
        section = ensure_default_teaching_section(batch)
        if not before and section is not None:
            created_defaults += 1

    to_fix = StudentProgrammeEnrollment.objects.filter(
        Q(teaching_section__isnull=True)
        | ~Q(teaching_section__program_batch_id=F("program_batch_id"))
    ).select_related("program_batch")

    for enrollment in to_fix.iterator():
        ensure_enrollment_teaching_section(enrollment, assign_only=False)
        assigned += 1

    return {
        "dry_run": False,
        "batches": len(batches),
        "defaults_created": created_defaults,
        "enrollments_assigned": assigned,
    }
