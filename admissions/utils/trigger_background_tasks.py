import logging

from admissions.tasks import celery_admission_email
from admissions.utils.student_portal_provisioning import provision_student_portal_on_admission

logger = logging.getLogger(__name__)


def send_admission_portal_credentials(admission_id: int) -> None:
    """Send login credentials after commit (used from on_commit hooks)."""
    from admissions.models import AdmittedStudent
    from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD
    from admissions.utils.email import send_student_login_credentials

    admission = AdmittedStudent.objects.select_related("student_user").filter(pk=admission_id).first()
    if not admission or not admission.student_user_id:
        return
    send_student_login_credentials(admission.student_user, DEFAULT_STUDENT_PASSWORD)


def queue_admission_notification_emails(admission_id: int, application_id: int) -> None:
    send_admission_portal_credentials(admission_id)
    celery_admission_email.delay(application_id, admission_id)


def trigger_background_tasks(admission_id, application_id):
    """
    Provision the student portal account synchronously, then queue admission email.

    Account creation must succeed before this returns; Celery is only used for email.
    """
    provision_student_portal_on_admission(admission_id, send_credentials_email=False)
    queue_admission_notification_emails(admission_id, application_id)
