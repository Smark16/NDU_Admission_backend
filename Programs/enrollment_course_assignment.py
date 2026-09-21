"""Resolve operational course units for auto-enrollment from curriculum + combination."""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .curriculum_inheritance import curriculum_owner_program, ensure_enrollment_curriculum_version
from .models import CourseUnit, ProgramCurriculumLine, Semester, StudentCurriculumOverride
from .specialization_rules import (
    compute_specialization_course_gate,
    normalize_specialization,
    resolve_specialization_for_program,
)


def ensure_enrollment_specialization_from_admission(enrollment) -> bool:
    """
    Copy the teaching subject combination chosen at admission onto the enrollment
    record when it is still blank (Faculty of Education and similar programmes).
    """
    if normalize_specialization(enrollment.specialization):
        return False

    from admissions.admission_specialization import admitted_subject_combination_label

    label = admitted_subject_combination_label(enrollment.student)
    if not label:
        return False

    program = enrollment.program
    matched, _err = resolve_specialization_for_program(program, label)
    enrollment.specialization = matched or label
    enrollment.save(update_fields=["specialization", "updated_at"])
    return True


def student_curriculum_includes_operational_unit(
    enrollment,
    course_unit,
    *,
    selected_specialization: str | None = None,
) -> bool:
    """
    True when the student's curriculum blueprint includes this operational unit's
    catalog course at their current term for their combination (or core).

    Education programmes often share one CourseUnit per code per semester across
    subject combinations; the unit's curriculum_line may point at another track.
    """
    if enrollment is None or course_unit is None:
        return False

    sem = course_unit.semester
    if sem is None:
        return False

    catalog_id = course_unit.catalog_unit_id
    code = (course_unit.code or "").strip()
    if not catalog_id and code:
        from .models import CourseCatalogUnit

        catalog_id = (
            CourseCatalogUnit.objects.filter(code__iexact=code)
            .values_list("id", flat=True)
            .first()
        )
    if not catalog_id:
        return False

    selected = normalize_specialization(
        selected_specialization if selected_specialization is not None else enrollment.specialization
    )
    program = enrollment.program
    curr_year = enrollment.current_year_of_study
    curr_term = enrollment.current_term_number
    curriculum_version = ensure_enrollment_curriculum_version(enrollment)

    lines = ProgramCurriculumLine.objects.filter(
        program=curriculum_owner_program(program),
        curriculum_version=curriculum_version,
        catalog_course_id=catalog_id,
        year_of_study=curr_year,
        term_number=curr_term,
        is_active=True,
    )
    if selected:
        lines = lines.filter(
            Q(specialization__isnull=True)
            | Q(specialization="")
            | Q(specialization__iexact=selected)
        )
    else:
        lines = lines.filter(Q(specialization__isnull=True) | Q(specialization=""))

    return lines.exists()


def _enrollment_entry_pair(enrollment) -> tuple[int, int]:
    try:
        ey = int(enrollment.entry_year_of_study) if enrollment.entry_year_of_study is not None else 1
    except (TypeError, ValueError):
        ey = 1
    try:
        et = int(enrollment.entry_term_number) if enrollment.entry_term_number is not None else 1
    except (TypeError, ValueError):
        et = 1
    return ey, et


def _year_term_billing_reached(enrollment, year_of_study: int, term_number: int) -> bool:
    """
    True when Accounts treats this curriculum term as billable / due.

    Mirrors remaining-tuition visibility: Y1S1 leftovers can be due while the
    student sits on Y2S1, but Y1S2 leftovers wait until that term's billing date.
    """
    from payments.billing_visibility import default_billing_date_for_year_term

    effective = default_billing_date_for_year_term(
        enrollment.program,
        enrollment.program_batch,
        int(year_of_study),
        int(term_number),
    )
    if effective is None:
        return True
    return timezone.localdate() >= effective


def _excluded_curriculum_line_ids(enrollment) -> set[int]:
    return set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred", "deferred"),
        ).values_list("curriculum_line_id", flat=True)
    )


def _active_lines_for_year_term(
    enrollment,
    *,
    year_of_study: int,
    term_number: int,
    selected: str,
    excluded_line_ids: set[int],
) -> list:
    curriculum_version = ensure_enrollment_curriculum_version(enrollment)
    lines = ProgramCurriculumLine.objects.filter(
        program=curriculum_owner_program(enrollment.program),
        curriculum_version=curriculum_version,
        year_of_study=year_of_study,
        term_number=term_number,
        is_active=True,
    ).exclude(id__in=excluded_line_ids)

    if selected:
        lines = lines.filter(
            Q(specialization__isnull=True)
            | Q(specialization="")
            | Q(specialization__iexact=selected)
        )
    return list(lines.select_related("catalog_course"))


def _course_unit_ids_for_lines(enrollment, year_of_study: int, term_number: int, line_list) -> list[int]:
    semester = (
        Semester.objects.filter(
            program_batch_id=enrollment.program_batch_id,
            year_of_study=year_of_study,
            term_number=term_number,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )
    if semester is None or not line_list:
        return []

    cu_by_code = {
        cu.code: cu.id
        for cu in CourseUnit.objects.filter(semester=semester, is_active=True).only("id", "code")
    }
    cu_by_line = {
        cu.curriculum_line_id: cu.id
        for cu in CourseUnit.objects.filter(
            semester=semester, is_active=True, curriculum_line_id__isnull=False
        ).only("id", "curriculum_line_id")
    }

    unit_ids: list[int] = []
    seen: set[int] = set()
    for line in line_list:
        cat = line.catalog_course
        code = cat.code if cat else None
        cid = cu_by_line.get(line.id) or (cu_by_code.get(code) if code else None)
        if cid and cid not in seen:
            seen.add(cid)
            unit_ids.append(cid)
    return unit_ids


def due_prior_year_term_pairs(enrollment) -> list[tuple[int, int]]:
    """
    Pre-entry curriculum terms whose remaining (non-exempted) papers are due now.

    After exemption promotion, entry is stamped to the new position (e.g. Y2T1).
    Non-exempted papers before entry are still owed; only terms whose billing
    date has been reached are due this semester (Accounts rule).

    Normal progressive students keep entry at Y1T1, so this returns nothing.
    """
    if not enrollment.program_batch_id:
        return []

    curr_year = int(enrollment.current_year_of_study)
    curr_term = int(enrollment.current_term_number)
    entry_pair = _enrollment_entry_pair(enrollment)
    curr_pair = (curr_year, curr_term)

    # Pre-entry leftover terms only (exemption / advanced standing). Normal
    # students keep entry at Y1T1 so this set is empty.
    ceiling = min(entry_pair, curr_pair)

    curriculum_version = ensure_enrollment_curriculum_version(enrollment)
    pairs = (
        ProgramCurriculumLine.objects.filter(
            program=curriculum_owner_program(enrollment.program),
            curriculum_version=curriculum_version,
            is_active=True,
        )
        .values_list("year_of_study", "term_number")
        .distinct()
    )

    due: list[tuple[int, int]] = []
    for y, t in sorted({(int(y), int(t)) for y, t in pairs}):
        if (y, t) >= ceiling:
            continue
        if (y, t) >= curr_pair:
            continue
        if _year_term_billing_reached(enrollment, y, t):
            due.append((y, t))
    return due


def course_unit_ids_for_enrollment_current_term(enrollment) -> tuple[list[int], str | None]:
    """
    Course units for the student's current year/term only (no pre-entry leftovers).

    Returns (course_unit_ids, skip_reason).
    """
    if not enrollment.program_batch_id:
        return [], "no_program_batch"

    ensure_enrollment_specialization_from_admission(enrollment)

    program = enrollment.program
    curr_year = enrollment.current_year_of_study
    curr_term = enrollment.current_term_number
    curriculum_version = ensure_enrollment_curriculum_version(enrollment)

    gate = compute_specialization_course_gate(
        program,
        curriculum_version,
        curr_year,
        curr_term,
        enrollment.specialization,
    )
    if gate["requires_specialization"]:
        return [], "specialization_required"

    selected = normalize_specialization(enrollment.specialization)
    excluded_line_ids = _excluded_curriculum_line_ids(enrollment)
    line_list = _active_lines_for_year_term(
        enrollment,
        year_of_study=curr_year,
        term_number=curr_term,
        selected=selected,
        excluded_line_ids=excluded_line_ids,
    )
    if not line_list:
        return [], f"no_curriculum_lines_y{curr_year}_t{curr_term}"

    semester = (
        Semester.objects.filter(
            program_batch_id=enrollment.program_batch_id,
            year_of_study=curr_year,
            term_number=curr_term,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )
    if semester is None:
        return [], f"no_active_semester_y{curr_year}_t{curr_term}"

    unit_ids = _course_unit_ids_for_lines(enrollment, curr_year, curr_term, line_list)
    if not unit_ids:
        return [], f"no_operational_course_units_semester_{semester.id}"

    return unit_ids, None


def course_unit_ids_for_enrollment_due_terms(enrollment) -> tuple[list[int], str | None]:
    """
    Units due now: current SPE term + pre-entry remaining papers whose term
    billing date has been reached. Skips exempted / transferred / deferred lines
    and does not pull later leftover terms early (e.g. Y1S2 while only Y1S1 is due).
    """
    unit_ids, skip_reason = course_unit_ids_for_enrollment_current_term(enrollment)
    # Current term missing is still a hard skip for activation; do not invent backlog-only.
    if skip_reason:
        return unit_ids, skip_reason

    selected = normalize_specialization(enrollment.specialization)
    excluded_line_ids = _excluded_curriculum_line_ids(enrollment)
    seen = set(unit_ids)

    for y, t in due_prior_year_term_pairs(enrollment):
        line_list = _active_lines_for_year_term(
            enrollment,
            year_of_study=y,
            term_number=t,
            selected=selected,
            excluded_line_ids=excluded_line_ids,
        )
        for cid in _course_unit_ids_for_lines(enrollment, y, t, line_list):
            if cid not in seen:
                seen.add(cid)
                unit_ids.append(cid)

    return unit_ids, None


def withdraw_enrollments_for_exempted_papers(enrollment) -> int:
    """
    Mark active enrollments withdrawn when the paper is exempted/transferred.

    Keeps My Courses / LMS aligned with curriculum overrides after promotion.
    """
    from .models import StudentCourseUnitEnrollment

    exempt_codes = set()
    for ov in (
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred"),
        ).select_related("curriculum_line__catalog_course")
    ):
        cat = ov.curriculum_line.catalog_course if ov.curriculum_line_id else None
        if cat and cat.code:
            exempt_codes.add(cat.code.strip().upper())

    if not exempt_codes:
        return 0

    qs = (
        StudentCourseUnitEnrollment.objects.filter(student=enrollment.student)
        .exclude(status="withdrawn")
        .select_related("course_unit")
    )
    withdrawn = 0
    for row in qs:
        code = (row.course_unit.code or "").strip().upper()
        if code in exempt_codes:
            row.status = "withdrawn"
            row.save(update_fields=["status"])
            withdrawn += 1
    return withdrawn


def withdraw_enrollments_for_not_yet_due_prior_terms(enrollment) -> int:
    """
    Withdraw enrollments for pre-entry leftover papers whose term is not due yet.

    Example: after promotion to Y2T1, Y1S2 remaining papers stay off My Courses
    until that term's billing date (same Accounts rule as remaining tuition).
    """
    from .models import StudentCourseUnitEnrollment

    entry_pair = _enrollment_entry_pair(enrollment)
    curr_pair = (
        int(enrollment.current_year_of_study),
        int(enrollment.current_term_number),
    )
    ceiling = min(entry_pair, curr_pair)
    # No advanced / exemption entry stamp → nothing to treat as premature leftover.
    if entry_pair <= (1, 1):
        return 0

    due_pairs = set(due_prior_year_term_pairs(enrollment))
    curr_year = int(enrollment.current_year_of_study)
    curr_term = int(enrollment.current_term_number)

    qs = (
        StudentCourseUnitEnrollment.objects.filter(student=enrollment.student)
        .exclude(status="withdrawn")
        .select_related("course_unit__semester")
    )
    withdrawn = 0
    for row in qs:
        sem = row.course_unit.semester
        if sem is None:
            continue
        pair = (int(sem.year_of_study), int(sem.term_number))
        if pair == (curr_year, curr_term):
            continue
        if pair >= ceiling:
            continue
        if pair in due_pairs:
            continue
        # Pre-entry leftover term not yet due — drop from active list.
        row.status = "withdrawn"
        row.save(update_fields=["status"])
        withdrawn += 1
    return withdrawn


def pending_exemption_covers_course_unit(course_unit_enrollment) -> bool:
    """
    True when the student has a not-yet-decided exemption request (AdmissionChangeRequest,
    status="pending") with a line matching this course unit's code + year/term.

    Used to gate un-registering a StudentCourseUnitEnrollment: registration is normally
    locked once set (see AdminDeregisterStudentFromCourses), but a student who registered
    for their normal course load before an overlapping exemption request was decided needs
    a way back into registration once that request resolves.
    """
    from admissions.models import AdmissionChangeRequest

    cu = course_unit_enrollment.course_unit
    sem = cu.semester
    code = (cu.code or "").strip().upper()
    if not code or sem is None:
        return False

    return AdmissionChangeRequest.objects.filter(
        admitted_student=course_unit_enrollment.student,
        change_type="exemption",
        status="pending",
        exemption_lines__course_code__iexact=code,
        exemption_lines__year_of_study=sem.year_of_study,
        exemption_lines__term_number=sem.term_number,
    ).exists()


def revoke_course_unit_registration(course_unit_enrollment) -> None:
    """
    Clear registration_date back to None (keep the enrollment + status="enrolled"),
    so the student can go through RegisterForCourses again. Also clears the
    student-level is_registered/registration_date flag when nothing else is registered.
    """
    from .models import StudentCourseUnitEnrollment

    course_unit_enrollment.registration_date = None
    course_unit_enrollment.save(update_fields=["registration_date"])

    student = course_unit_enrollment.student
    still_registered = (
        StudentCourseUnitEnrollment.objects.filter(student=student)
        .exclude(status="withdrawn")
        .filter(registration_date__isnull=False)
        .exists()
    )
    if not still_registered and student.is_registered:
        student.is_registered = False
        student.registration_date = None
        student.save(update_fields=["is_registered", "registration_date"])
