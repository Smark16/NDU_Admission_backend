"""Activate academic programme enrollment after commitment fee payment."""
from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from admissions.models import AdmittedStudent

from .models import RegistrationSettings
from .student_portal_finance import commitment_payment_summary

logger = logging.getLogger(__name__)


def try_activate_programme_enrollment_after_payment(
    student: AdmittedStudent | None,
) -> dict | None:
    """
    Idempotent entry point for payment signals and SchoolPay ledger sync.
    Reloads the student row so admission_fee_paid and ledger credits are current.
    """
    if student is None or not getattr(student, "pk", None):
        return None
    fresh = (
        AdmittedStudent.objects.filter(pk=student.pk, is_admitted=True)
        .select_related(
            "admitted_program",
            "admitted_batch",
            "intended_program_batch",
        )
        .first()
    )
    if fresh is None:
        return None
    return activate_programme_enrollment_after_commitment_payment(fresh)


def _default_program_batch(student: AdmittedStudent):
    if not student.admitted_program_id:
        return None

    from Programs.program_batch_resolution import resolve_default_program_batch_for_program

    ipb = getattr(student, "intended_program_batch", None)
    if ipb is not None and ipb.program_id != student.admitted_program_id:
        ipb = None
    if ipb is not None:
        return ipb

    return resolve_default_program_batch_for_program(
        student.admitted_program,
        admission_batch=student.admitted_batch,
    )


def _auto_assign_current_semester_course_units(enrollment) -> dict:
    """Auto-assign course units for the student's current term (combination-aware)."""
    from Programs.enrollment_course_assignment import course_unit_ids_for_enrollment_current_term
    from Programs.models import StudentCourseUnitEnrollment, StudentProgrammeEnrollment

    def _zero(reason: str) -> dict:
        return {
            "course_units_auto_assigned": 0,
            "course_units_total_in_semester": 0,
            "auto_assign_skip_reason": reason,
        }

    settings = RegistrationSettings.get_settings()
    if not getattr(settings, "auto_assign_course_units_after_commitment", True):
        return _zero("toggle_disabled")

    enrollment = (
        StudentProgrammeEnrollment.objects.select_related(
            "student",
            "student__admitted_specialization",
            "program",
            "program_batch",
        ).get(pk=enrollment.pk)
    )

    unit_ids, skip_reason = course_unit_ids_for_enrollment_current_term(enrollment)
    if skip_reason:
        return _zero(skip_reason)
    if not unit_ids:
        return _zero("no_course_units")

    existing_ids = set(
        StudentCourseUnitEnrollment.objects.filter(
            student=enrollment.student, course_unit_id__in=unit_ids
        ).values_list("course_unit_id", flat=True)
    )
    missing_ids = [cid for cid in unit_ids if cid not in existing_ids]
    if missing_ids:
        StudentCourseUnitEnrollment.objects.bulk_create(
            [
                StudentCourseUnitEnrollment(
                    student=enrollment.student,
                    course_unit_id=cid,
                    status="enrolled",
                    source="admin_assigned",
                )
                for cid in missing_ids
            ],
            ignore_conflicts=True,
        )
    return {
        "course_units_auto_assigned": len(missing_ids),
        "course_units_total_in_semester": len(unit_ids),
        "auto_assign_skip_reason": None,
    }


def activate_programme_enrollment(
    student: AdmittedStudent,
    *,
    activated_by=None,
    require_commitment: bool = True,
    mark_admission_fee_paid: bool | None = None,
    note: str | None = None,
) -> dict:
    """
    Move StudentProgrammeEnrollment to status='enrolled'.

    When ``require_commitment`` is True (default), commitment fee must be met.
    When False (RegistrationSettings.auto_enroll_on_admission), unpaid admitted
    students can still be academically enrolled.
    """
    from Programs.models import (
        StudentProgrammeEnrollment,
        resolve_program_default_curriculum_version,
    )

    if not student.is_admitted:
        return {"activated": False, "reason": "not_admitted"}

    summary = commitment_payment_summary(student)
    if require_commitment and not summary["commitment_met"]:
        return {"activated": False, "reason": "commitment_not_met", **summary}

    if mark_admission_fee_paid is None:
        mark_admission_fee_paid = bool(require_commitment and summary["commitment_met"])

    default_note = (
        "Auto-enrolled after commitment fee payment."
        if require_commitment
        else "Auto-enrolled on admission (commitment gate skipped by registration settings)."
    )
    activation_note = (note or default_note).strip()

    with transaction.atomic():
        # Avoid select_related() on nullable relations with FOR UPDATE:
        # PostgreSQL rejects row locks on the nullable side of outer joins.
        locked_student = AdmittedStudent.objects.select_for_update().get(pk=student.pk)

        # Keep the denormalized bonafide flag in sync when commitment is actually met.
        # Do not fake admission_fee_paid when skipping the commitment gate.
        if mark_admission_fee_paid and not locked_student.admission_fee_paid:
            locked_student.admission_fee_paid = True
            locked_student.admission_fee_paid_at = timezone.now()
            locked_student.save(
                update_fields=["admission_fee_paid", "admission_fee_paid_at", "updated_at"]
            )

        try:
            enrollment = locked_student.programme_enrollment
        except StudentProgrammeEnrollment.DoesNotExist:
            enrollment = None

        if enrollment is None:
            program_batch = _default_program_batch(locked_student)
            if program_batch is None:
                return {"activated": False, "reason": "no_program_batch"}

            curriculum_version = None
            if program_batch.curriculum_version_id:
                curriculum_version = program_batch.curriculum_version
            elif locked_student.admitted_program_id:
                curriculum_version = resolve_program_default_curriculum_version(
                    locked_student.admitted_program
                )

            from admissions.admission_specialization import admitted_subject_combination_label

            enrollment = StudentProgrammeEnrollment.objects.create(
                student=locked_student,
                program=locked_student.admitted_program,
                program_batch=program_batch,
                curriculum_version=curriculum_version,
                current_year_of_study=1,
                current_term_number=1,
                specialization=admitted_subject_combination_label(locked_student) or "",
                status="enrolled",
                enrolled_by=activated_by,
                enrolled_at=timezone.now(),
                notes=activation_note,
            )
            logger.info(
                "Created enrolled SPE for student %s (%s)",
                locked_student.student_id,
                "commitment" if require_commitment else "auto_enroll_on_admission",
            )
            auto_assign_result = _auto_assign_current_semester_course_units(enrollment)
            return {
                "activated": True,
                "reason": "created_enrolled",
                "enrollment_id": enrollment.id,
                **auto_assign_result,
            }

        if enrollment.status == "enrolled":
            auto_assign_result = _auto_assign_current_semester_course_units(enrollment)
            return {
                "activated": False,
                "reason": "already_enrolled",
                "enrollment_id": enrollment.id,
                **auto_assign_result,
            }

        if enrollment.status != "pending":
            return {
                "activated": False,
                "reason": f"status_{enrollment.status}",
                "enrollment_id": enrollment.id,
            }

        enrollment.status = "enrolled"
        if activated_by is not None:
            enrollment.enrolled_by = activated_by
        if not enrollment.enrolled_at:
            enrollment.enrolled_at = timezone.now()
        enrollment.notes = (
            f"{enrollment.notes}\n{activation_note}".strip()
            if enrollment.notes
            else activation_note
        )
        enrollment.save()

        logger.info(
            "Activated SPE %s for student %s (%s)",
            enrollment.id,
            locked_student.student_id,
            "commitment" if require_commitment else "auto_enroll_on_admission",
        )
        auto_assign_result = _auto_assign_current_semester_course_units(enrollment)
        return {
            "activated": True,
            "reason": "activated",
            "enrollment_id": enrollment.id,
            **auto_assign_result,
        }


def activate_programme_enrollment_after_commitment_payment(
    student: AdmittedStudent,
    *,
    activated_by=None,
) -> dict:
    """Move SPE to enrolled once commitment fee threshold is met."""
    return activate_programme_enrollment(
        student,
        activated_by=activated_by,
        require_commitment=True,
    )


def activate_all_pending_programme_enrollments(*, activated_by=None) -> dict:
    """Promote pending enrollments to enrolled only when commitment fee is met."""
    from Programs.models import StudentProgrammeEnrollment

    pending = StudentProgrammeEnrollment.objects.filter(status="pending").select_related(
        "student",
        "student__admitted_program",
        "student__admitted_batch",
        "student__intended_program_batch",
    )
    activated = 0
    skipped = 0
    course_units_assigned = 0
    for enrollment in pending:
        result = activate_programme_enrollment_after_commitment_payment(
            enrollment.student,
            activated_by=activated_by,
        )
        if result.get("activated"):
            activated += 1
            course_units_assigned += result.get("course_units_auto_assigned", 0) or 0
        else:
            skipped += 1

    return {
        "activated_count": activated,
        "skipped_count": skipped,
        "course_units_auto_assigned": course_units_assigned,
    }


def enroll_all_admitted_skipping_commitment(*, activated_by=None) -> dict:
    """
    Academically enroll every admitted student (create SPE or promote pending).

    Used when RegistrationSettings.auto_enroll_on_admission is turned ON.
    Does not mark unpaid students as admission_fee_paid.
    """
    from Programs.models import StudentProgrammeEnrollment

    spe_enrolled = StudentProgrammeEnrollment.objects.filter(
        student_id=OuterRef("pk"), status="enrolled"
    )
    candidates = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .filter(Q(admitted_program_id__isnull=False))
        .exclude(Exists(spe_enrolled))
        .select_related(
            "admitted_program",
            "admitted_batch",
            "intended_program_batch",
        )
        .order_by("pk")
    )

    activated = 0
    skipped = 0
    course_units_assigned = 0
    skip_reasons: dict[str, int] = {}

    # Avoid .iterator() — breaks on some remote Postgres / PgBouncer setups.
    last_pk = 0
    while True:
        batch = list(candidates.filter(pk__gt=last_pk).order_by("pk")[:200])
        if not batch:
            break
        for student in batch:
            result = activate_programme_enrollment(
                student,
                activated_by=activated_by,
                require_commitment=False,
                mark_admission_fee_paid=False,
            )
            if result.get("activated"):
                activated += 1
                course_units_assigned += result.get("course_units_auto_assigned", 0) or 0
            else:
                skipped += 1
                reason = str(result.get("reason") or "unknown")
                skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
        last_pk = batch[-1].pk

    return {
        "activated_count": activated,
        "skipped_count": skipped,
        "course_units_auto_assigned": course_units_assigned,
        "skip_reasons": skip_reasons,
        "candidates": activated + skipped,
    }
