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
    """Queue admission decision email (credentials are sent synchronously on admit)."""
    try:
        celery_admission_email.delay(application_id, admission_id)
    except Exception:
        logger.exception(
            "Failed to queue admission email for application=%s admission=%s",
            application_id,
            admission_id,
        )


def trigger_background_tasks(admission_id, application_id):
    """
    Provision portal account + credentials synchronously, then queue admission email.

    Used by bulk import paths that commit before notifying.
    """
    provision_student_portal_on_admission(admission_id, send_credentials_email=True)
    queue_admission_notification_emails(admission_id, application_id)
