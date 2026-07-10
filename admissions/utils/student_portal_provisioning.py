"""Synchronous student portal account + enrollment on admission."""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class StudentPortalProvisioningError(Exception):
    """Raised when a portal user cannot be created for an admitted student."""


def auto_enroll_admitted_student(admission, acting_user_id: int | None) -> None:
    from Programs.models import StudentProgrammeEnrollment
    from Programs.program_batch_resolution import resolve_default_program_batch_for_program
    from payments.admin_enrollment_requirements import (
        admin_programme_enrollment_activation_block,
    )

    try:
        today = timezone.now().date()
        program_batch = admission.intended_program_batch or resolve_default_program_batch_for_program(
            admission.admitted_program,
            today=today,
            admission_batch=admission.admitted_batch,
        )
        if not program_batch:
            return

        from django.contrib.auth import get_user_model

        User = get_user_model()
        acting_user = User.objects.filter(pk=acting_user_id).first() if acting_user_id else None

        activation_block = admin_programme_enrollment_activation_block(
            admission, target_status="enrolled"
        )
        enroll_status = "enrolled" if activation_block is None else "pending"

        StudentProgrammeEnrollment.objects.get_or_create(
            student=admission,
            defaults={
                "program": admission.admitted_program,
                "program_batch": program_batch,
                "current_year_of_study": 1,
                "current_term_number": 1,
                "status": enroll_status,
                "enrolled_by": acting_user if enroll_status == "enrolled" else None,
                "enrolled_at": timezone.now() if enroll_status == "enrolled" else None,
            },
        )
    except Exception:
        logger.exception("Auto-enrollment failed for admission %s", admission.pk)


def provision_student_portal_on_admission(
    admission_id: int,
    *,
    send_credentials_email: bool = True,
) -> None:
    """
    Create/link the student portal user immediately when a student is admitted.

    Runs in-process (not Celery). Raises StudentPortalProvisioningError on failure.
    """
    from admissions.models import AdmittedStudent
    from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, ensure_student_portal_account
    from admissions.utils.email import send_student_login_credentials

    admission = (
        AdmittedStudent.objects.select_related(
            "application__applicant",
            "student_user",
            "admitted_program",
            "admitted_batch",
            "intended_program_batch",
        )
        .filter(pk=admission_id)
        .first()
    )
    if not admission:
        raise StudentPortalProvisioningError("Admission record not found.")

    if not (admission.reg_no or "").strip():
        raise StudentPortalProvisioningError(
            "Registration number is required before a student portal account can be created."
        )

    had_linked_user = bool(admission.student_user_id)
    user, created = ensure_student_portal_account(
        admission,
        reset_password=not had_linked_user,
    )
    if user is None:
        raise StudentPortalProvisioningError(
            "Student portal account could not be created. Check the registration number."
        )

    if send_credentials_email and (created or not had_linked_user):
        sent = send_student_login_credentials(
            user, DEFAULT_STUDENT_PASSWORD, admission=admission
        )
        if not sent:
            logger.warning(
                "Portal account created for admission %s but credentials email failed.",
                admission_id,
            )

    auto_enroll_admitted_student(admission, admission.admitted_by_id)
    admission.refresh_from_db(fields=["student_user"])
    assert_student_portal_ready(admission)


def assert_student_portal_ready(admission) -> None:
    """Raise if the admitted student cannot sign in to the student portal."""
    from admissions.student_accounts import student_portal_username

    user = admission.student_user
    if user is None:
        raise StudentPortalProvisioningError(
            f"Portal account was not linked for admission {admission.pk}."
        )
    if not user.is_active:
        raise StudentPortalProvisioningError(
            f"Portal account for {admission.reg_no} is inactive."
        )
    if not user.is_student:
        raise StudentPortalProvisioningError(
            f"Portal account for {admission.reg_no} is not marked as a student."
        )
    expected_username = student_portal_username(admission.reg_no)
    if expected_username and user.username.lower() != expected_username.lower():
        raise StudentPortalProvisioningError(
            f"Portal username mismatch for {admission.reg_no}: "
            f"expected {expected_username}, got {user.username}."
        )
