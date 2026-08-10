"""Section-scoped lecturer assignment on course units."""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q


def sync_course_unit_lecturers_m2m(course_unit) -> None:
    """Keep CourseUnit.lecturers as the union of all section assignments."""
    from Programs.models import CourseUnitSectionLecturer

    ids = list(
        CourseUnitSectionLecturer.objects.filter(course_unit_id=course_unit.pk)
        .values_list("lecturer_id", flat=True)
        .distinct()
    )
    course_unit.lecturers.set(ids)


def resolve_section_for_course_unit(course_unit, raw_section_id):
    """Return TeachingSection or None (ALL). Raises ValueError on bad id."""
    from Programs.models import TeachingSection
    from Programs.teaching_sections import resolve_program_batch_for_course_unit

    if raw_section_id in (None, "", "null", "none", "all", "ALL"):
        return None
    try:
        section_id = int(raw_section_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("teaching_section_id must be an integer or empty for all sections.") from exc

    from Programs.teaching_sections import section_covers_batch

    batch = resolve_program_batch_for_course_unit(course_unit)
    if batch is None:
        raise ValueError("Course unit has no academic cohort for teaching sections.")

    try:
        section = TeachingSection.objects.get(pk=section_id, is_active=True)
    except TeachingSection.DoesNotExist as exc:
        raise ValueError("Teaching section not found on this course unit's cohort.") from exc
    if not section_covers_batch(section, batch.pk):
        raise ValueError("Teaching section not found on this course unit's cohort.")
    return section


@transaction.atomic
def assign_lecturers_to_section(
    course_unit,
    lecturer_ids: list[int],
    *,
    teaching_section=None,
    mode: str = "replace",
) -> dict:
    """
    Set lecturers for one scope (ALL or a specific section).

    mode="replace" — lecturer_ids become the full set for this scope.
    mode="add" — lecturer_ids are merged into the existing set for this scope.
    Other section assignments on the same unit are left intact.
    """
    from accounts.models import User
    from Programs.models import CourseUnit, CourseUnitSectionLecturer

    requested_ids = list(dict.fromkeys(int(x) for x in lecturer_ids))
    lecturers = list(
        User.objects.filter(
            id__in=requested_ids, is_active=True
        ).filter(Q(is_staff=True) | Q(is_lecturer=True))
    )
    if len(lecturers) != len(requested_ids):
        raise ValueError("Some selected users are not active staff or lecturers.")

    scope_qs = CourseUnitSectionLecturer.objects.filter(course_unit=course_unit)
    if teaching_section is None:
        scope_qs = scope_qs.filter(teaching_section__isnull=True)
    else:
        scope_qs = scope_qs.filter(teaching_section=teaching_section)

    previous_ids = set(scope_qs.values_list("lecturer_id", flat=True))
    if str(mode).lower() == "add":
        final_ids = previous_ids | {l.id for l in lecturers}
        lecturers = list(
            User.objects.filter(id__in=final_ids).order_by("last_name", "first_name")
        )
    else:
        final_ids = {l.id for l in lecturers}

    scope_qs.delete()

    for lec in lecturers:
        CourseUnitSectionLecturer.objects.create(
            course_unit=course_unit,
            teaching_section=teaching_section,
            lecturer=lec,
        )
        if not lec.is_lecturer:
            lec.is_lecturer = True
            lec.save(update_fields=["is_lecturer"])

    sync_course_unit_lecturers_m2m(course_unit)

    removed_ids = previous_ids - final_ids
    for uid in removed_ids:
        still = CourseUnit.objects.filter(lecturers__id=uid).exists()
        if not still:
            User.objects.filter(id=uid).update(is_lecturer=False)

    return {
        "teaching_section_id": teaching_section.id if teaching_section else None,
        "teaching_section_code": teaching_section.code if teaching_section else "ALL",
        "lecturers": [
            {"id": l.id, "name": l.get_full_name(), "email": l.email} for l in lecturers
        ],
        "count": len(lecturers),
    }


@transaction.atomic
def remove_lecturer_from_section(course_unit, lecturer, *, teaching_section=None) -> None:
    from accounts.models import User
    from Programs.models import CourseUnit, CourseUnitSectionLecturer

    qs = CourseUnitSectionLecturer.objects.filter(
        course_unit=course_unit, lecturer=lecturer
    )
    if teaching_section is None:
        qs = qs.filter(teaching_section__isnull=True)
    else:
        qs = qs.filter(teaching_section=teaching_section)
    qs.delete()

    # If no scoped rows left but still on M2M from legacy, clean M2M via sync
    if not CourseUnitSectionLecturer.objects.filter(
        course_unit=course_unit, lecturer=lecturer
    ).exists():
        course_unit.lecturers.remove(lecturer)
    else:
        sync_course_unit_lecturers_m2m(course_unit)

    if not CourseUnit.objects.filter(lecturers=lecturer).exists():
        lecturer.is_lecturer = False
        lecturer.save(update_fields=["is_lecturer"])


def backfill_section_lecturers_from_m2m() -> int:
    """Create ALL-scope rows from existing CourseUnit.lecturers M2M."""
    from Programs.models import CourseUnit, CourseUnitSectionLecturer

    created = 0
    for cu in CourseUnit.objects.prefetch_related("lecturers").iterator():
        for lec in cu.lecturers.all():
            _, was_created = CourseUnitSectionLecturer.objects.get_or_create(
                course_unit=cu,
                teaching_section=None,
                lecturer=lec,
            )
            if was_created:
                created += 1
    return created


def list_lecturers_by_section(course_unit) -> dict:
    from Programs.models import CourseUnitSectionLecturer
    from Programs.teaching_sections import (
        list_sections_for_batch,
        resolve_program_batch_for_course_unit,
    )

    rows = (
        CourseUnitSectionLecturer.objects.filter(course_unit=course_unit)
        .select_related("lecturer", "teaching_section")
        .order_by("teaching_section__code", "lecturer__last_name")
    )

    all_lecturers = {}
    by_section: dict[str, dict] = {
        "all": {
            "teaching_section_id": None,
            "code": "ALL",
            "name": "All sections (shared)",
            "is_default": False,
            "lecturers": [],
        }
    }

    batch = resolve_program_batch_for_course_unit(course_unit)
    if batch is not None:
        for s in list_sections_for_batch(batch.pk):
            by_section[str(s["id"])] = {
                "teaching_section_id": s["id"],
                "code": s["code"],
                "name": s["name"],
                "is_default": s.get("is_default"),
                "lecturers": [],
            }

    for row in rows:
        lec = {
            "id": row.lecturer_id,
            "name": row.lecturer.get_full_name(),
            "email": row.lecturer.email,
            "teaching_section_id": row.teaching_section_id,
            "teaching_section_code": (
                row.teaching_section.code if row.teaching_section_id else "ALL"
            ),
        }
        all_lecturers[row.lecturer_id] = {
            "id": row.lecturer_id,
            "name": lec["name"],
            "email": lec["email"],
        }
        key = str(row.teaching_section_id) if row.teaching_section_id else "all"
        if key not in by_section:
            by_section[key] = {
                "teaching_section_id": row.teaching_section_id,
                "code": lec["teaching_section_code"],
                "name": lec["teaching_section_code"],
                "is_default": False,
                "lecturers": [],
            }
        by_section[key]["lecturers"].append(lec)

    # Legacy fallback: M2M only, no section rows yet
    if not rows.exists():
        for lec in course_unit.lecturers.all():
            all_lecturers[lec.id] = {
                "id": lec.id,
                "name": lec.get_full_name(),
                "email": lec.email,
            }
            by_section["all"]["lecturers"].append(
                {
                    "id": lec.id,
                    "name": lec.get_full_name(),
                    "email": lec.email,
                    "teaching_section_id": None,
                    "teaching_section_code": "ALL",
                }
            )

    return {
        "lecturers": list(all_lecturers.values()),
        "by_section": list(by_section.values()),
    }


def user_teaches_timetable_session(user, session) -> bool:
    """Whether this lecturer should see a published timetable session."""
    from Programs.models import CourseUnitSectionLecturer

    cu = session.course_unit
    assignments = CourseUnitSectionLecturer.objects.filter(
        course_unit_id=cu.pk, lecturer_id=user.pk
    )
    if assignments.exists():
        if session.teaching_section_id is None:
            # Shared lecture: anyone assigned on the unit (any section or ALL)
            return True
        return assignments.filter(
            Q(teaching_section__isnull=True)
            | Q(teaching_section_id=session.teaching_section_id)
        ).exists()

    # Legacy M2M only
    return cu.lecturers.filter(pk=user.pk).exists()
