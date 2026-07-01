"""Synchronous student portal account + enrollment on admission."""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


class StudentPortalProvisioningError(Exception):
    """Raised when a portal user cannot be created for an admitted student."""


def auto_enroll_admitted_student(admission, acting_user_id: int | None) -> None:
    from payments.models import RegistrationSettings
    from Programs.models import StudentProgrammeEnrollment
    from Programs.program_batch_resolution import resolve_default_program_batch_for_program

    try:
        reg_settings = RegistrationSettings.get_settings()
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

        StudentProgrammeEnrollment.objects.get_or_create(
            student=admission,
            defaults={
                "program": admission.admitted_program,
                "program_batch": program_batch,
                "current_year_of_study": 1,
                "current_term_number": 1,
                "status": "enrolled" if reg_settings.auto_enroll_on_admission else "pending",
                "enrolled_by": acting_user if reg_settings.auto_enroll_on_admission else None,
                "enrolled_at": timezone.now() if reg_settings.auto_enroll_on_admission else None,
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
    user, created = ensure_student_portal_account(admission)
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
