"""Activate academic programme enrollment after commitment fee payment."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent

from .models import RegistrationSettings
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


def _auto_assign_current_semester_course_units(enrollment) -> dict:
    """Auto-assign course units in student's current active semester when enabled."""
    from Programs.models import CourseUnit, Semester, StudentCourseUnitEnrollment

    def _zero(reason: str) -> dict:
        return {
            "course_units_auto_assigned": 0,
            "course_units_total_in_semester": 0,
            "auto_assign_skip_reason": reason,
        }

    settings = RegistrationSettings.get_settings()
    if not getattr(settings, "auto_assign_course_units_after_commitment", True):
        return _zero("toggle_disabled")

    if not enrollment.program_batch_id:
        return _zero("no_program_batch")

    semester = (
        Semester.objects.filter(
            program_batch_id=enrollment.program_batch_id,
            year_of_study=enrollment.current_year_of_study,
            term_number=enrollment.current_term_number,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )
    if semester is None:
        return _zero(
            f"no_active_semester_y{enrollment.current_year_of_study}_t{enrollment.current_term_number}"
        )

    units = list(
        CourseUnit.objects.filter(semester=semester, is_active=True).only("id")
    )
    if not units:
        return _zero(f"no_active_course_units_semester_{semester.id}")

    unit_ids = [u.id for u in units]
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
        # Avoid select_related() on nullable relations with FOR UPDATE:
        # PostgreSQL rejects row locks on the nullable side of outer joins.
        locked_student = AdmittedStudent.objects.select_for_update().get(pk=student.pk)

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
        note = "Auto-enrolled after commitment fee payment."
        enrollment.notes = f"{enrollment.notes}\n{note}".strip() if enrollment.notes else note
        enrollment.save()

        logger.info(
            "Activated SPE %s for student %s after commitment payment",
            enrollment.id,
            locked_student.student_id,
        )
        auto_assign_result = _auto_assign_current_semester_course_units(enrollment)
        return {
            "activated": True,
            "reason": "activated",
            "enrollment_id": enrollment.id,
            **auto_assign_result,
        }
