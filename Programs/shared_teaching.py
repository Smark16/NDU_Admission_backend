"""Helpers for SharedTeachingOffering — common courses across programmes."""
from __future__ import annotations

from django.db.models import QuerySet

from .models import CourseUnit, SharedTeachingOffering, StudentCourseUnitEnrollment


def moodle_idnumber_for_course_unit(cu: CourseUnit) -> str:
    """Moodle course key: shared offering when linked, else legacy code-semester."""
    if cu.shared_teaching_offering_id:
        offering = getattr(cu, "shared_teaching_offering", None)
        if offering is not None and offering.pk:
            return offering.moodle_idnumber
        return f"STO-{cu.shared_teaching_offering_id}"
    return f"{cu.code}-{cu.semester_id}"


def linked_course_unit_ids(course_unit: CourseUnit) -> list[int]:
    """All CourseUnit PKs that share teaching with this one (at least itself)."""
    if not course_unit.shared_teaching_offering_id:
        return [course_unit.pk]
    return list(
        CourseUnit.objects.filter(
            shared_teaching_offering_id=course_unit.shared_teaching_offering_id,
            is_active=True,
        ).values_list("id", flat=True)
    )


def linked_course_units_qs(course_unit: CourseUnit) -> QuerySet[CourseUnit]:
    ids = linked_course_unit_ids(course_unit)
    return CourseUnit.objects.filter(id__in=ids, is_active=True)


def registered_enrollments_for_course_unit(
    course_unit: CourseUnit,
    *,
    statuses: list[str] | None = None,
) -> QuerySet[StudentCourseUnitEnrollment]:
    """Roster for LMS / marks: merges all programme CourseUnits on the same offering."""
    if statuses is None:
        statuses = ["enrolled"]
    cu_ids = linked_course_unit_ids(course_unit)
    return (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit_id__in=cu_ids,
            status__in=statuses,
            registration_date__isnull=False,
        )
        .select_related(
            "student",
            "student__application",
            "student__admitted_program",
            "course_unit",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "course_unit__semester",
        )
        .order_by("student__reg_no", "id")
    )


def serialize_shared_offering(offering: SharedTeachingOffering) -> dict:
    units = list(
        offering.course_units.filter(is_active=True)
        .select_related("program_batch", "program_batch__program", "semester")
        .order_by("code", "id")
    )
    lecturers = [
        {
            "id": u.id,
            "name": u.get_full_name() or u.username,
            "email": u.email or "",
        }
        for u in offering.lecturers.all()
    ]
    return {
        "id": offering.id,
        "code": offering.code,
        "name": offering.name,
        "catalog_unit_id": offering.catalog_unit_id,
        "academic_year_label": offering.academic_year_label,
        "year_of_study": offering.year_of_study,
        "term_number": offering.term_number,
        "exam_paper_code": offering.exam_paper_code,
        "paper_code": offering.paper_code,
        "moodle_idnumber": offering.moodle_idnumber,
        "notes": offering.notes,
        "is_active": offering.is_active,
        "lecturers": lecturers,
        "course_units": [
            {
                "id": cu.id,
                "code": cu.code,
                "name": cu.name,
                "semester_id": cu.semester_id,
                "semester_name": cu.semester.name if cu.semester_id else None,
                "program_batch_id": cu.program_batch_id,
                "program_batch_name": cu.program_batch.name if cu.program_batch_id else None,
                "program_id": cu.program_batch.program_id if cu.program_batch_id else None,
                "program_name": (
                    cu.program_batch.program.name
                    if cu.program_batch_id and cu.program_batch.program_id
                    else None
                ),
            }
            for cu in units
        ],
        "linked_count": len(units),
        "created_at": offering.created_at.isoformat() if offering.created_at else None,
        "updated_at": offering.updated_at.isoformat() if offering.updated_at else None,
    }


def create_shared_offering_from_course_units(
    *,
    course_unit_ids: list[int],
    code: str | None = None,
    name: str | None = None,
    academic_year_label: str = "",
    year_of_study: int | None = None,
    term_number: int | None = None,
    exam_paper_code: str = "",
    notes: str = "",
    lecturer_ids: list[int] | None = None,
) -> SharedTeachingOffering:
    """Create an offering and link the given programme CourseUnits to it."""
    units = list(
        CourseUnit.objects.filter(id__in=course_unit_ids, is_active=True).select_related(
            "catalog_unit"
        )
    )
    if len(units) < 2:
        raise ValueError("Link at least two active course units to create a shared offering.")

    codes = {u.code.strip() for u in units if u.code}
    if len(codes) > 1:
        # Allow if caller forces a canonical code; otherwise require same code.
        if not (code or "").strip():
            raise ValueError(
                f"Course units have different codes ({', '.join(sorted(codes))}). "
                "Pass an explicit canonical code."
            )

    primary = units[0]
    offering = SharedTeachingOffering.objects.create(
        code=(code or primary.code or "").strip(),
        name=(name or primary.name or "").strip(),
        catalog_unit_id=primary.catalog_unit_id,
        academic_year_label=(academic_year_label or "").strip(),
        year_of_study=year_of_study,
        term_number=term_number,
        exam_paper_code=(exam_paper_code or "").strip(),
        notes=(notes or "").strip(),
        is_active=True,
    )
    CourseUnit.objects.filter(id__in=[u.id for u in units]).update(
        shared_teaching_offering_id=offering.id
    )
    if lecturer_ids:
        offering.lecturers.set(lecturer_ids)
    else:
        # Union lecturers already on the linked units
        from django.contrib.auth import get_user_model

        User = get_user_model()
        lids = set()
        for u in units:
            lids.update(u.lecturers.values_list("id", flat=True))
        if lids:
            offering.lecturers.set(User.objects.filter(id__in=lids))
    return offering
