"""Activate academic programme enrollment after commitment fee payment."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent

from .student_portal_finance import commitment_payment_summary

logger = logging.getLogger(__name__)


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


def activate_programme_enrollment_after_commitment_payment(
    student: AdmittedStudent,
    *,
    activated_by=None,
) -> dict:
    """
    Move StudentProgrammeEnrollment to status='enrolled' once completed UGX
    tuition payments meet the commitment threshold.
    """
    from Programs.models import (
        StudentProgrammeEnrollment,
        resolve_program_default_curriculum_version,
    )

    if not student.is_admitted:
        return {"activated": False, "reason": "not_admitted"}

    summary = commitment_payment_summary(student)
    if not summary["commitment_met"]:
        return {"activated": False, "reason": "commitment_not_met", **summary}

    with transaction.atomic():
        locked_student = (
            AdmittedStudent.objects.select_for_update()
            .select_related("admitted_program", "programme_enrollment")
            .get(pk=student.pk)
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

            enrollment = StudentProgrammeEnrollment.objects.create(
                student=locked_student,
                program=locked_student.admitted_program,
                program_batch=program_batch,
                curriculum_version=curriculum_version,
                current_year_of_study=1,
                current_term_number=1,
                status="enrolled",
                enrolled_by=activated_by,
                enrolled_at=timezone.now(),
                notes="Auto-enrolled after commitment fee payment.",
            )
            logger.info(
                "Created enrolled SPE for student %s after commitment payment",
                locked_student.student_id,
            )
            return {
                "activated": True,
                "reason": "created_enrolled",
                "enrollment_id": enrollment.id,
            }

        if enrollment.status == "enrolled":
            return {
                "activated": False,
                "reason": "already_enrolled",
                "enrollment_id": enrollment.id,
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
        note = "Auto-enrolled after commitment fee payment."
        enrollment.notes = f"{enrollment.notes}\n{note}".strip() if enrollment.notes else note
        enrollment.save()

        logger.info(
            "Activated SPE %s for student %s after commitment payment",
            enrollment.id,
            locked_student.student_id,
        )
        return {
            "activated": True,
            "reason": "activated",
            "enrollment_id": enrollment.id,
        }
