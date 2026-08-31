"""Teaching sections within an academic cohort (ProgramBatch), including shared ones."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Count, F, Q

logger = logging.getLogger(__name__)

DEFAULT_SECTION_CODE = "MAIN"
DEFAULT_SECTION_NAME = "Main"
# Extra A/B sections may warn at this size. The default MAIN catch-all is unlimited.
DEFAULT_MAX_CAPACITY = 120
DEFAULT_SECTION_MAX_CAPACITY = 0


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


def section_covers_batch(section, program_batch_id: int | None) -> bool:
    """True if the section's owning or linked cohorts include this batch."""
    if section is None or not program_batch_id:
        return False
    if section.program_batch_id == program_batch_id:
        return True
    if not getattr(section, "is_shared", False):
        return False
    linked = getattr(section, "linked_batches", None)
    if linked is None:
        return False
    return linked.filter(pk=program_batch_id).exists()


def serialize_section(section, *, student_count: int | None = None) -> dict:
    if student_count is None:
        student_count = section_headcount(section)

    linked = []
    if getattr(section, "is_shared", False):
        # Prefer prefetched relation when available
        try:
            batches = list(section.linked_batches.select_related("program").all())
        except Exception:
            batches = []
        linked = [
            {
                "id": b.id,
                "name": b.name,
                "program_id": b.program_id,
                "program_name": b.program.name if b.program_id else None,
                "program_code": getattr(b.program, "short_form", None) if b.program_id else None,
            }
            for b in batches
        ]

    owner_program = None
    try:
        owner_program = section.program_batch.program
    except Exception:
        owner_program = None

    return {
        "id": section.id,
        "program_batch_id": section.program_batch_id,
        "owner_program_id": getattr(owner_program, "id", None),
        "owner_program_code": getattr(owner_program, "short_form", None),
        "owner_batch_name": (
            section.program_batch.name
            if getattr(section, "program_batch_id", None)
            else None
        ),
        "code": section.code,
        "name": section.name,
        "is_default": section.is_default,
        "is_shared": bool(section.is_shared),
        "linked_batches": linked,
        "linked_batch_ids": [b["id"] for b in linked],
        "max_capacity": section.max_capacity,
        "is_active": section.is_active,
        "student_count": student_count,
        "at_or_over_capacity": (
            section.max_capacity > 0 and student_count >= section.max_capacity
        ),
    }


def ensure_default_teaching_section(program_batch, *, max_capacity: int = DEFAULT_SECTION_MAX_CAPACITY):
    """
    Ensure the cohort has exactly one default teaching section.
    Creates MAIN / Main when missing. Default capacity is 0 (unlimited) so the
    full cohort is visible; split sections can still use a cap.
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
        if existing.max_capacity != 0:
            existing.max_capacity = 0
            existing.save(update_fields=["max_capacity", "updated_at"])
        return existing

    from django.core.exceptions import MultipleObjectsReturned

    try:
        section, created = TeachingSection.objects.get_or_create(
            program_batch_id=program_batch.pk,
            code=DEFAULT_SECTION_CODE,
            defaults={
                "name": DEFAULT_SECTION_NAME,
                "is_default": True,
                "is_shared": False,
                "max_capacity": max_capacity,
                "is_active": True,
            },
        )
    except MultipleObjectsReturned:
        # Legacy duplicates — pick the default row instead of failing placement saves.
        section = (
            TeachingSection.objects.filter(
                program_batch_id=program_batch.pk,
                code=DEFAULT_SECTION_CODE,
            )
            .order_by("-is_default", "id")
            .first()
        )
        created = False
        if section is None:
            return None
    if not section.is_default:
        if not TeachingSection.objects.filter(
            program_batch_id=program_batch.pk, is_default=True
        ).exists():
            section.is_default = True
            section.save(update_fields=["is_default", "updated_at"])
    if section.is_default and section.max_capacity != 0:
        section.max_capacity = 0
        section.save(update_fields=["max_capacity", "updated_at"])
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
    when the current section does not cover this cohort (including shared).

    When assign_only=True, only mutates the in-memory instance (for use inside save()).
    """
    from Programs.models import TeachingSection

    if enrollment is None or not enrollment.program_batch_id:
        return enrollment

    needs = False
    if not enrollment.teaching_section_id:
        needs = True
    else:
        section = getattr(enrollment, "teaching_section", None)
        if section is None or not getattr(section, "pk", None):
            section = TeachingSection.objects.filter(pk=enrollment.teaching_section_id).first()
        if section is None:
            needs = True
        elif not section_covers_batch(section, enrollment.program_batch_id):
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


def list_peer_batches_for_sharing(program_batch_id: int) -> list[dict]:
    """Other active cohorts in the same faculty (candidates for shared sections)."""
    from Programs.models import ProgramBatch

    batch = (
        ProgramBatch.objects.select_related("program__faculty")
        .filter(pk=program_batch_id)
        .first()
    )
    if batch is None or not batch.program_id:
        return []
    faculty_id = getattr(batch.program, "faculty_id", None)
    if not faculty_id:
        return []

    peers = (
        ProgramBatch.objects.filter(
            program__faculty_id=faculty_id,
            is_active=True,
        )
        .exclude(pk=batch.pk)
        .select_related("program")
        .order_by("program__name", "name")
    )
    return [
        {
            "id": b.id,
            "name": b.name,
            "program_id": b.program_id,
            "program_name": b.program.name,
            "program_code": getattr(b.program, "short_form", None),
            "academic_year": b.academic_year or "",
        }
        for b in peers[:300]
    ]


def list_sections_for_batch(program_batch_id: int) -> list[dict]:
    from Programs.models import ProgramBatch, TeachingSection

    batch = ProgramBatch.objects.filter(pk=program_batch_id).first()
    if batch is None:
        return []
    ensure_default_teaching_section(batch)

    qs = (
        TeachingSection.objects.filter(
            Q(program_batch_id=program_batch_id)
            | Q(is_shared=True, linked_batches__id=program_batch_id)
        )
        .select_related("program_batch__program")
        .prefetch_related("linked_batches__program")
        .annotate(student_count=Count("student_enrollments", distinct=True))
        .distinct()
        .order_by("-is_default", "-is_shared", "code", "name")
    )
    return [serialize_section(s, student_count=s.student_count) for s in qs]


def get_section_for_batch_or_raise(section_id: int, program_batch_id: int):
    """Return active/usable section that covers this batch, or raise ValueError."""
    from Programs.models import TeachingSection

    section = (
        TeachingSection.objects.select_related("program_batch__program")
        .prefetch_related("linked_batches")
        .filter(pk=section_id)
        .first()
    )
    if section is None:
        raise ValueError("Teaching section not found.")
    if not section_covers_batch(section, program_batch_id):
        raise ValueError("Teaching section is not available on this academic cohort.")
    return section


def validate_linked_batches(*, owner_batch, linked_batch_ids: list[int]) -> list:
    """Ensure linked batches exist, differ from owner, and share the same faculty."""
    from Programs.models import ProgramBatch

    ids = sorted({int(x) for x in linked_batch_ids if x is not None})
    ids = [i for i in ids if i != owner_batch.pk]
    if not ids:
        raise ValueError(
            "Shared sections require at least one other programme batch "
            "in the same faculty."
        )

    faculty_id = getattr(owner_batch.program, "faculty_id", None)
    if not faculty_id:
        raise ValueError("Owning programme has no faculty; cannot create a shared section.")

    batches = list(
        ProgramBatch.objects.filter(pk__in=ids).select_related("program")
    )
    if len(batches) != len(ids):
        raise ValueError("One or more linked programme batches were not found.")

    for b in batches:
        if getattr(b.program, "faculty_id", None) != faculty_id:
            raise ValueError(
                f"Batch '{b}' is not in the same faculty as the owning cohort."
            )
        if not b.is_active:
            raise ValueError(f"Batch '{b}' is inactive and cannot be linked.")
    return batches


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
    Move programme enrollments into a teaching section that covers this cohort
    (own section or shared section linked to this batch).
    ``student_ids`` are AdmittedStudent PKs; ``enrollment_ids`` are SPE PKs.
    """
    from Programs.models import ProgramBatch, StudentProgrammeEnrollment, TeachingSection

    try:
        batch = ProgramBatch.objects.get(pk=program_batch_id)
    except ProgramBatch.DoesNotExist as exc:
        raise ValueError("Academic programme batch not found.") from exc

    try:
        target = TeachingSection.objects.select_for_update().get(pk=target_section_id)
    except TeachingSection.DoesNotExist as exc:
        raise ValueError("Target teaching section not found.") from exc

    if not section_covers_batch(target, batch.pk):
        raise ValueError("Target teaching section is not available on this cohort.")

    if not target.is_active:
        raise ValueError("Target teaching section is inactive.")

    # of=("self",) is required: teaching_section is a nullable FK, and Postgres
    # rejects FOR UPDATE on the nullable side of an outer join from select_related.
    qs = StudentProgrammeEnrollment.objects.select_for_update(of=("self",)).filter(
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
        "is_shared": bool(target.is_shared),
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
        needing = 0
        for enrollment in StudentProgrammeEnrollment.objects.filter(
            Q(teaching_section__isnull=True)
            | ~Q(teaching_section__program_batch_id=F("program_batch_id"))
        ).iterator():
            section = enrollment.teaching_section
            if enrollment.teaching_section_id is None:
                needing += 1
            elif section is None or not section_covers_batch(
                section, enrollment.program_batch_id
            ):
                needing += 1
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

    # Only reset rows whose section does not cover their cohort (shared OK).
    candidates = StudentProgrammeEnrollment.objects.filter(
        Q(teaching_section__isnull=True)
        | ~Q(teaching_section__program_batch_id=F("program_batch_id"))
    ).select_related("program_batch", "teaching_section")

    for enrollment in candidates.iterator():
        section = enrollment.teaching_section
        if enrollment.teaching_section_id and section is not None:
            if section_covers_batch(section, enrollment.program_batch_id):
                continue
        ensure_enrollment_teaching_section(enrollment, assign_only=False)
        assigned += 1

    return {
        "dry_run": False,
        "batches": len(batches),
        "defaults_created": created_defaults,
        "enrollments_assigned": assigned,
    }
