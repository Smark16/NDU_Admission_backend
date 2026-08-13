"""Course registration: set registration_date on StudentCourseUnitEnrollment."""
from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent


def _unit_allowed_for_self_register(student, cu, spe) -> tuple[bool, str]:
    """
    Align with GetAvailableCoursesForRegistration: students may register for
    current-term (or deferred/backlog) offerings even when admin auto-assign
    never created a StudentCourseUnitEnrollment row.
    """
    if spe is None:
        return False, (
            f"Not enrolled in {cu.code}; programme enrollment is missing. "
            "Contact admissions/registry."
        )
    if not cu.is_active:
        return False, f"{cu.code} is not active."

    from Programs.models import StudentCurriculumOverride

    if cu.curriculum_line_id:
        blocked = (
            StudentCurriculumOverride.objects.filter(
                enrollment=spe,
                curriculum_line_id=cu.curriculum_line_id,
                override_type__in=("exempted", "transferred"),
            )
            .values_list("override_type", flat=True)
            .first()
        )
        if blocked:
            return False, f"{cu.code} is marked {blocked} and cannot be registered."

    sem = cu.semester
    if sem is None:
        return False, f"{cu.code} has no semester assigned."

    if spe.program_batch_id and sem.program_batch_id != spe.program_batch_id:
        return False, f"{cu.code} is not on your academic cohort."

    if (
        sem.year_of_study == spe.current_year_of_study
        and sem.term_number == spe.current_term_number
    ):
        return True, ""

    if cu.curriculum_line_id and StudentCurriculumOverride.objects.filter(
        enrollment=spe,
        curriculum_line_id=cu.curriculum_line_id,
        override_type__in=("deferred", "backlog"),
        effective_year_of_study=spe.current_year_of_study,
        effective_term_number=spe.current_term_number,
    ).exists():
        return True, ""

    # Legacy semesters without year/term metadata on the same cohort.
    if (sem.year_of_study is None or sem.term_number is None) and (
        spe.program_batch_id and sem.program_batch_id == spe.program_batch_id
    ):
        return True, ""

    return False, (
        f"Cannot register for {cu.code}: it is not offered for your current term "
        f"(Year {spe.current_year_of_study}, Term {spe.current_term_number})."
    )


def register_student_for_course_units(student: AdmittedStudent, course_unit_ids: list) -> dict:
    from Programs.models import CourseUnit, StudentCourseUnitEnrollment, StudentProgrammeEnrollment
    from examinations.models import ExamRetakeRegistration
    from examinations.services.outstanding_papers import offering_meta_by_course_unit_id
    from payments.retake_fees import ensure_retake_fee_for_enrollment

    registered = []
    errors = []
    t = timezone.now()
    spe = (
        StudentProgrammeEnrollment.objects.select_related("program", "program_batch")
        .filter(student=student)
        .first()
    )
    selected_specialization = (spe.specialization or "").strip() if spe else ""
    retake_meta = offering_meta_by_course_unit_id(student)
    ids = []
    for x in course_unit_ids:
        if x is None:
            continue
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            errors.append(f"Invalid course id: {x}")
    with transaction.atomic():
        for cid in ids:
            try:
                cu = CourseUnit.objects.select_related(
                    "curriculum_line", "semester", "semester__program_batch"
                ).get(id=cid)
            except CourseUnit.DoesNotExist:
                errors.append(f"Course unit {cid} not found")
                continue

            offering = retake_meta.get(cid)
            is_retake_offer = offering is not None

            # Protect specialization tracks at write-time too (not just list-time).
            if cu.curriculum_line_id and not is_retake_offer:
                line_spec = (cu.curriculum_line.specialization or "").strip()
                if line_spec and not selected_specialization:
                    errors.append(
                        f"{cu.code} requires a specialization to be selected before registration."
                    )
                    continue
                if line_spec and selected_specialization.lower() != line_spec.lower():
                    errors.append(
                        f"{cu.code} belongs to '{line_spec}' specialization, not '{selected_specialization}'."
                    )
                    continue

            en = StudentCourseUnitEnrollment.objects.filter(student=student, course_unit=cu).first()
            if not en:
                if is_retake_offer:
                    kind = offering.get("registration_kind") or StudentCourseUnitEnrollment.KIND_RETAKE
                    en = StudentCourseUnitEnrollment.objects.create(
                        student=student,
                        course_unit=cu,
                        status="enrolled",
                        source="self_registered",
                        registration_kind=kind,
                    )
                else:
                    allowed, reason = _unit_allowed_for_self_register(student, cu, spe)
                    if not allowed:
                        errors.append(reason)
                        continue
                    en = StudentCourseUnitEnrollment.objects.create(
                        student=student,
                        course_unit=cu,
                        status="enrolled",
                        source="self_registered",
                    )
            if en.registration_date:
                errors.append(f"Already registered for {cu.code}")
                continue

            if is_retake_offer:
                kind = offering.get("registration_kind") or StudentCourseUnitEnrollment.KIND_RETAKE
                en.registration_kind = kind
            en.registration_date = t
            en.save()

            fee = None
            if is_retake_offer:
                fee = ensure_retake_fee_for_enrollment(
                    student,
                    en,
                    registration_kind=en.registration_kind,
                )
                active = ExamRetakeRegistration.objects.filter(
                    enrollment=en,
                    status__in=(
                        ExamRetakeRegistration.STATUS_PENDING,
                        ExamRetakeRegistration.STATUS_APPROVED,
                        ExamRetakeRegistration.STATUS_SCHEDULED,
                    ),
                ).first()
                if active is None:
                    ExamRetakeRegistration.objects.create(
                        enrollment=en,
                        status=ExamRetakeRegistration.STATUS_APPROVED,
                        reason=(
                            f"{offering.get('paper_outcome', 'retake')} — "
                            f"{offering.get('original_semester_label', '')}"
                        ).strip()[:2000],
                        reviewed_at=t,
                    )
                elif active.status == ExamRetakeRegistration.STATUS_PENDING:
                    active.status = ExamRetakeRegistration.STATUS_APPROVED
                    active.reviewed_at = t
                    active.save(update_fields=["status", "reviewed_at"])
            row = {
                "id": en.id,
                "course_code": cu.code,
                "course_name": cu.name,
                "registration_kind": en.registration_kind,
            }
            if fee is not None:
                row["retake_fee"] = {
                    "id": fee.id,
                    "amount": float(fee.amount),
                    "currency": fee.currency,
                    "label": fee.label,
                    "status": fee.status,
                }
            registered.append(row)
        if registered:
            student.is_registered = True
            if not student.registration_date:
                student.registration_date = t
            student.save()
    return {"registered": registered, "errors": errors, "registration_time": t}
