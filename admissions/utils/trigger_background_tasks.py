import logging

from admissions.tasks import celery_admission_email
from admissions.utils.student_portal_provisioning import provision_student_portal_on_admission

logger = logging.getLogger(__name__)


def send_admission_portal_credentials(admission_id: int) -> None:
    """Resend login credentials (e.g. manual retry). Prefer provision on admit."""
    from admissions.models import AdmittedStudent
    from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD
    from admissions.utils.email import send_student_login_credentials

    admission = (
        AdmittedStudent.objects.select_related("student_user", "application")
        .filter(pk=admission_id)
        .first()
    )
    if not admission or not admission.student_user_id:
        logger.warning(
            "Cannot send portal credentials: admission %s has no student_user.",
            admission_id,
        )
        return
    send_student_login_credentials(
        admission.student_user,
        DEFAULT_STUDENT_PASSWORD,
        admission=admission,
    )


def queue_admission_notification_emails(admission_id: int, application_id: int) -> None:
    """Queue admission decision email + student portal notification (credentials already sent)."""
    try:
        celery_admission_email.delay(application_id, admission_id)
    except Exception:
        logger.exception(
            "Failed to queue admission email for application=%s admission=%s",
            application_id,
            admission_id,
        )
    try:
        from admissions.models import AdmittedStudent
        from admissions.tasks import celery_application_notification
        from accounts.portal_branding import get_university_display_name

        admission = (
            AdmittedStudent.objects.select_related("student_user", "application__applicant")
            .filter(pk=admission_id)
            .first()
        )
        if not admission:
            return
        student_user = admission.student_user or getattr(
            getattr(admission, "application", None), "applicant", None
        )
        if not student_user:
            return
        uni = get_university_display_name()
        celery_application_notification.delay(
            student_user.id,
            "Admission Successful",
            f"Congratulations! You have been admitted to {uni}.",
        )
    except Exception:
        logger.exception(
            "Failed to queue admission portal notification for admission=%s",
            admission_id,
        )


def trigger_background_tasks(admission_id, application_id):
    """
    Provision portal account + credentials synchronously, then queue admission email.

    Used by bulk import paths that commit before notifying.
    """
    provision_student_portal_on_admission(admission_id, send_credentials_email=True)
    queue_admission_notification_emails(admission_id, application_id)
