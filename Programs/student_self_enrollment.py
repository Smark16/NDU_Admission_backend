"""Student-initiated academic programme enrollment (pending or enrolled)."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from admissions.admission_specialization import admitted_subject_combination_label
from admissions.models import AdmittedStudent

from .models import StudentProgrammeEnrollment, resolve_program_default_curriculum_version


def _resolve_program_batch(student: AdmittedStudent):
    from Programs.program_batch_resolution import resolve_default_program_batch_for_program

    ipb = getattr(student, "intended_program_batch", None)
    if ipb is not None and student.admitted_program_id and ipb.program_id != student.admitted_program_id:
        ipb = None
    if ipb is not None:
        return ipb
    if not student.admitted_program_id:
        return None
    return resolve_default_program_batch_for_program(
        student.admitted_program,
        admission_batch=student.admitted_batch,
    )


def student_self_enroll(admitted: AdmittedStudent) -> dict:
    """
    Let an admitted student enroll themselves.

    - Commitment fee met → status Enrolled (+ auto course assign via payment activation)
    - Not paid → status Pending (shows interest; no course registration)
    """
    from payments.programme_enrollment_activation import (
        activate_programme_enrollment_after_commitment_payment,
    )
    from payments.student_portal_finance import commitment_payment_summary

    if not admitted.is_admitted:
        return {"ok": False, "reason": "not_admitted", "detail": "You must be admitted before enrolling."}

    app = getattr(admitted, "application", None)
    if app and getattr(app, "is_revoked", False):
        return {"ok": False, "reason": "revoked", "detail": "Your admission has been revoked."}

    summary = commitment_payment_summary(admitted)
    if summary["commitment_met"]:
        result = activate_programme_enrollment_after_commitment_payment(admitted)
        activated = bool(result.get("activated")) or result.get("reason") in (
            "created_enrolled",
            "already_enrolled",
        )
        try:
            enrollment = admitted.programme_enrollment
        except StudentProgrammeEnrollment.DoesNotExist:
            enrollment = None
        return {
            "ok": True,
            "status": enrollment.status if enrollment else "enrolled",
            "commitment_met": True,
            "activated": activated,
            "created": result.get("reason") == "created_enrolled",
            "enrollment_id": result.get("enrollment_id"),
            "course_units_auto_assigned": result.get("course_units_auto_assigned", 0),
            "detail": (
                "You are enrolled. Your courses have been assigned."
                if enrollment and enrollment.is_enrolled
                else "Enrollment could not be completed."
            ),
        }

    program_batch = _resolve_program_batch(admitted)
    if program_batch is None:
        return {
            "ok": False,
            "reason": "no_program_batch",
            "detail": (
                "Your programme batch is not configured yet. "
                "Please contact the Admissions Office."
            ),
        }

    program = admitted.admitted_program
    curriculum_version = None
    if program_batch.curriculum_version_id:
        curriculum_version = program_batch.curriculum_version
    elif program:
        curriculum_version = resolve_program_default_curriculum_version(program)

    combo = admitted_subject_combination_label(admitted) or ""

    with transaction.atomic():
        locked = (
            AdmittedStudent.objects.select_for_update()
            .select_related("admitted_program", "admitted_specialization", "programme_enrollment")
            .get(pk=admitted.pk)
        )
        try:
            enrollment = locked.programme_enrollment
        except StudentProgrammeEnrollment.DoesNotExist:
            enrollment = None

        if enrollment is None:
            enrollment = StudentProgrammeEnrollment.objects.create(
                student=locked,
                program=program,
                program_batch=program_batch,
                curriculum_version=curriculum_version,
                current_year_of_study=1,
                current_term_number=1,
                specialization=combo,
                status="pending",
                notes="Self-enrolled by student (commitment fee pending).",
            )
            created = True
        else:
            created = False
            if enrollment.status == "withdrawn":
                return {
                    "ok": False,
                    "reason": "withdrawn",
                    "detail": "Your enrollment was withdrawn. Contact the Admissions Office.",
                }
            if enrollment.status == "suspended":
                return {
                    "ok": False,
                    "reason": "suspended",
                    "detail": "Your enrollment is suspended. Contact the Admissions Office.",
                }
            updates = []
            if not (enrollment.specialization or "").strip() and combo:
                enrollment.specialization = combo
                updates.append("specialization")
            if enrollment.program_batch_id != program_batch.id:
                enrollment.program_batch = program_batch
                updates.append("program_batch")
            if curriculum_version and enrollment.curriculum_version_id is None:
                enrollment.curriculum_version = curriculum_version
                updates.append("curriculum_version")
            if enrollment.status != "pending" and enrollment.status != "enrolled":
                enrollment.status = "pending"
                updates.append("status")
            if updates:
                enrollment.save(update_fields=[*updates, "updated_at"])

        if locked.intended_program_batch_id is None:
            locked.intended_program_batch = program_batch
            locked.save(update_fields=["intended_program_batch", "updated_at"])

    return {
        "ok": True,
        "status": "pending",
        "commitment_met": False,
        "created": created,
        "enrollment_id": enrollment.id,
        "commitment_threshold": summary["commitment_threshold"],
        "commitment_paid_ugx": summary["commitment_paid_ugx"],
        "commitment_balance": summary["commitment_balance"],
        "detail": (
            "You are registered as interested in this programme. "
            "Pay the commitment fee (UGX 150,000) to activate full enrollment and course access."
        ),
    }
