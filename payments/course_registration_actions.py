"""Course registration: set registration_date on StudentCourseUnitEnrollment."""
from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent


def register_student_for_course_units(student: AdmittedStudent, course_unit_ids: list) -> dict:
    from Programs.models import CourseUnit, StudentCourseUnitEnrollment, StudentProgrammeEnrollment
    from examinations.models import ExamRetakeRegistration
    from examinations.services.outstanding_papers import offering_meta_by_course_unit_id
    from payments.retake_fees import ensure_retake_fee_for_enrollment

    registered = []
    errors = []
    t = timezone.now()
    spe = (
        StudentProgrammeEnrollment.objects.select_related("program")
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
                cu = CourseUnit.objects.select_related("curriculum_line", "semester").get(id=cid)
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
                if not is_retake_offer:
                    errors.append(f"Not enrolled in {cu.code}; ask admin to enroll you first.")
                    continue
                kind = offering.get("registration_kind") or StudentCourseUnitEnrollment.KIND_RETAKE
                en = StudentCourseUnitEnrollment.objects.create(
                    student=student,
                    course_unit=cu,
                    status="enrolled",
                    source="self_registered",
                    registration_kind=kind,
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
