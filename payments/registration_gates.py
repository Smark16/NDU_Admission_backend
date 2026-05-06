"""Registration window and admission/batch gates (before tuition % check)."""
from typing import Optional

from django.utils import timezone

from admissions.models import AdmittedStudent

from .models import RegistrationSettings


def settings_block_message(settings: RegistrationSettings) -> Optional[str]:
    if not settings.is_active:
        return "Course registration is currently disabled."
    now = timezone.now()
    if settings.registration_start_date and now < settings.registration_start_date:
        return "Course registration has not opened yet."
    if settings.registration_end_date and now > settings.registration_end_date:
        return "The course registration period has ended."
    return None


def enrollment_block(student: AdmittedStudent, settings: RegistrationSettings) -> Optional[str]:
    """Check admission status and programme enrollment gates.

    Priority order:
    1. Admission approval gate (require_admission_approval)
    2. Academic programme enrollment gate (require_programme_enrollment) — checks
       StudentProgrammeEnrollment.status == 'enrolled' (commitment fee confirmed).
    3. Legacy admission intake batch gate (require_enrollment) — kept for backward
       compatibility with students who have no SPE record yet.
    """
    # Gate 1: Must be admitted
    if settings.require_admission_approval and not student.is_admitted:
        return "You must be admitted before you can register."

    # Gate 2: Must have an active StudentProgrammeEnrollment (commitment fee gate)
    if settings.require_programme_enrollment:
        try:
            enrollment = student.programme_enrollment  # OneToOne reverse from SPE
            if not enrollment.is_enrolled:
                status_display = enrollment.get_status_display()
                return (
                    f"Your academic enrollment status is '{status_display}'. "
                    "Course registration is only available once your enrollment is "
                    "activated (commitment fee confirmed). Please contact the Admissions Office."
                )
        except Exception:
            # No StudentProgrammeEnrollment record at all
            return (
                "You do not have an active academic programme enrollment. "
                "Please contact the Admissions Office to confirm your commitment fee payment."
            )

    # Gate 3: Legacy — require admission intake batch (old flow)
    elif settings.require_enrollment and not student.admitted_batch_id:
        return "You must be assigned to an admission intake batch before you can register."

    return None


def get_programme_enrollment_status(student: AdmittedStudent) -> dict:
    """Return a dict describing the student's academic enrollment, for inclusion in API responses."""
    try:
        enrollment = student.programme_enrollment
        return {
            "has_programme_enrollment": True,
            "programme_enrollment_status": enrollment.status,
            "programme_enrollment_status_display": enrollment.get_status_display(),
            "is_programme_enrolled": enrollment.is_enrolled,
            "programme_name": enrollment.program.name if enrollment.program_id else None,
            "programme_batch": enrollment.program_batch.name if enrollment.program_batch_id else None,
            "current_year_of_study": enrollment.current_year_of_study,
            "current_term_number": enrollment.current_term_number,
        }
    except Exception:
        return {
            "has_programme_enrollment": False,
            "programme_enrollment_status": None,
            "programme_enrollment_status_display": "No enrollment record",
            "is_programme_enrolled": False,
            "programme_name": None,
            "programme_batch": None,
            "current_year_of_study": None,
            "current_term_number": None,
        }
