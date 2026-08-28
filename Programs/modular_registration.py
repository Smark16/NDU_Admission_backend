"""Module registration for programmes with calendar_type=modular."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q

from Programs.calendar_utils import program_is_modular


def _normalize_code(code: str | None) -> str:
    return (code or "").strip().upper()


def curriculum_catalog_unit_ids(spe) -> set[int]:
    from Programs.curriculum_inheritance import (
        curriculum_owner_program,
        ensure_enrollment_curriculum_version,
    )
    from Programs.models import ProgramCurriculumLine

    if spe is None or not spe.program_id:
        return set()
    curriculum_version = ensure_enrollment_curriculum_version(spe)
    owner = curriculum_owner_program(spe.program)
    return set(
        ProgramCurriculumLine.objects.filter(
            program=owner,
            curriculum_version=curriculum_version,
            is_active=True,
        ).values_list("catalog_course_id", flat=True)
    )


def curriculum_catalog_codes(spe) -> set[str]:
    from Programs.curriculum_inheritance import (
        curriculum_owner_program,
        ensure_enrollment_curriculum_version,
    )
    from Programs.models import ProgramCurriculumLine

    if spe is None or not spe.program_id:
        return set()
    curriculum_version = ensure_enrollment_curriculum_version(spe)
    owner = curriculum_owner_program(spe.program)
    codes = ProgramCurriculumLine.objects.filter(
        program=owner,
        curriculum_version=curriculum_version,
        is_active=True,
    ).values_list("catalog_course__code", flat=True)
    return {_normalize_code(c) for c in codes if c}


def current_session_semester(spe):
    from Programs.models import Semester

    if spe is None or not spe.program_batch_id:
        return None
    return (
        Semester.objects.filter(
            program_batch_id=spe.program_batch_id,
            year_of_study=spe.current_year_of_study,
            term_number=spe.current_term_number,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )


def completed_course_unit_ids(student) -> set[int]:
    from Programs.models import StudentCourseUnitEnrollment

    return set(
        StudentCourseUnitEnrollment.objects.filter(
            student=student,
            status="completed",
        ).values_list("course_unit_id", flat=True)
    )


def course_unit_in_program_curriculum(cu, catalog_unit_ids: set[int], catalog_codes: set[str]) -> bool:
    if not catalog_unit_ids and not catalog_codes:
        return True
    if cu.catalog_unit_id and cu.catalog_unit_id in catalog_unit_ids:
        return True
    code = _normalize_code(cu.code)
    if code and code in catalog_codes:
        return True
    if cu.catalog_unit_id and cu.catalog_unit:
        return _normalize_code(cu.catalog_unit.code) in catalog_codes
    return False


def modular_available_course_unit_ids(
    *,
    spe,
    student,
    registered_course_ids: set[int],
) -> set[int]:
    """Offerings in the current session the student may register for."""
    from Programs.models import CourseUnit

    if spe is None or not program_is_modular(spe.program):
        return set()

    batch_id = spe.program_batch_id
    if not batch_id:
        return set()

    catalog_unit_ids = curriculum_catalog_unit_ids(spe)
    catalog_codes = curriculum_catalog_codes(spe)
    completed = completed_course_unit_ids(student)

    ids: set[int] = set()
    session = current_session_semester(spe)
    if session:
        for cu in CourseUnit.objects.filter(
            semester_id=session.pk,
            is_active=True,
        ).select_related("catalog_unit"):
            if course_unit_in_program_curriculum(cu, catalog_unit_ids, catalog_codes):
                ids.add(cu.id)

    # Session slots without year/term metadata on the same cohort.
    for cu in CourseUnit.objects.filter(
        is_active=True,
        semester__program_batch_id=batch_id,
        semester__is_active=True,
    ).filter(
        Q(semester__year_of_study__isnull=True) | Q(semester__term_number__isnull=True)
    ).select_related("catalog_unit", "semester"):
        if course_unit_in_program_curriculum(cu, catalog_unit_ids, catalog_codes):
            ids.add(cu.id)

    ids -= registered_course_ids
    ids -= completed
    return ids


def modular_unit_allowed_for_register(student, cu, spe) -> tuple[bool, str]:
    if spe is None:
        return False, "Programme enrollment is missing. Contact registry."
    if not program_is_modular(spe.program):
        return False, "Not a modular programme."
    if not cu.is_active:
        return False, f"{cu.code} is not active."

    sem = cu.semester
    if sem is None:
        return False, f"{cu.code} has no session assigned."

    if spe.program_batch_id and sem.program_batch_id != spe.program_batch_id:
        return False, f"{cu.code} is not on your intake cohort."

    catalog_unit_ids = curriculum_catalog_unit_ids(spe)
    catalog_codes = curriculum_catalog_codes(spe)
    if not course_unit_in_program_curriculum(cu, catalog_unit_ids, catalog_codes):
        return False, f"{cu.code} is not part of your programme module list."

    if cu.id in completed_course_unit_ids(student):
        return False, f"You have already completed {cu.code}."

    session = current_session_semester(spe)
    on_current_session = bool(
        session
        and sem.pk == session.pk
    )
    loose_session = sem.year_of_study is None or sem.term_number is None
    if not on_current_session and not loose_session:
        return False, (
            f"{cu.code} is not offered in your current session "
            f"(Year {spe.current_year_of_study}, Session {spe.current_term_number})."
        )

    return True, ""


def modular_session_registered_credits(student, spe) -> Decimal:
    from Programs.models import StudentCourseUnitEnrollment

    session = current_session_semester(spe)
    if session is None:
        return Decimal("0")

    total = Decimal("0")
    qs = StudentCourseUnitEnrollment.objects.filter(
        student=student,
        registration_date__isnull=False,
        course_unit__semester_id=session.pk,
    ).select_related("course_unit")
    for en in qs:
        cu = en.course_unit
        if cu and cu.credit_units is not None:
            total += cu.credit_units
    return total


def modular_credit_limits(program) -> dict:
    return {
        "min_per_session": (
            float(program.modular_min_credits_per_session)
            if program.modular_min_credits_per_session is not None
            else None
        ),
        "max_per_session": (
            float(program.modular_max_credits_per_session)
            if program.modular_max_credits_per_session is not None
            else None
        ),
        "minimum_graduation_load": (
            float(program.minimum_graduation_load)
            if program.minimum_graduation_load is not None
            else None
        ),
    }


def validate_modular_registration_credits(
    *,
    student,
    spe,
    course_units,
) -> tuple[bool, str]:
    program = spe.program if spe else None
    if program is None or not program_is_modular(program):
        return True, ""

    max_c = program.modular_max_credits_per_session
    if max_c is None:
        return True, ""

    existing = modular_session_registered_credits(student, spe)
    adding = Decimal("0")
    for cu in course_units:
        if cu.credit_units is not None:
            adding += cu.credit_units
    if existing + adding > max_c:
        return False, (
            f"Registration would exceed the session limit of {max_c} credit units "
            f"(currently {existing}, adding {adding})."
        )
    return True, ""
