"""Resolve operational course units for auto-enrollment from curriculum + combination."""
from __future__ import annotations

from django.db.models import Q

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


def course_unit_ids_for_enrollment_current_term(enrollment) -> tuple[list[int], str | None]:
    """
    Course units the student should receive for their current year/term, using the
    same curriculum + specialization rules as portal registration.

    Returns (course_unit_ids, skip_reason). skip_reason is set when nothing can
    be assigned (missing semester, combination required but absent, etc.).
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

    excluded_line_ids = set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred", "deferred"),
        ).values_list("curriculum_line_id", flat=True)
    )

    lines = ProgramCurriculumLine.objects.filter(
        program=curriculum_owner_program(program),
        curriculum_version=curriculum_version,
        year_of_study=curr_year,
        term_number=curr_term,
        is_active=True,
    ).exclude(id__in=excluded_line_ids)

    if selected:
        lines = lines.filter(
            Q(specialization__isnull=True)
            | Q(specialization="")
            | Q(specialization__iexact=selected)
        )

    line_list = list(lines.select_related("catalog_course"))
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
        cid = cu_by_line.get(line.id) or cu_by_code.get(line.catalog_course.code)
        if cid and cid not in seen:
            seen.add(cid)
            unit_ids.append(cid)

    if not unit_ids:
        return [], f"no_operational_course_units_semester_{semester.id}"

    return unit_ids, None
