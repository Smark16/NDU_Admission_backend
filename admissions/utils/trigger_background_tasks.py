import logging

from admissions.tasks import celery_admission_email, celery_create_student_account
from admissions.student_accounts import ensure_student_portal_account, DEFAULT_STUDENT_PASSWORD

logger = logging.getLogger(__name__)


def provision_student_portal_account_sync(admission_id: int) -> None:
    """
    Create/link the student portal user immediately on admission.

    Celery may be offline; without this step many admitted students have no login at all.
    """
    from admissions.models import AdmittedStudent

    try:
        admission = AdmittedStudent.objects.select_related(
            "application__applicant", "student_user"
        ).get(pk=admission_id)
        user, created = ensure_student_portal_account(admission)
        if user and created:
            from admissions.tasks import celery_send_student_credentials_email

            celery_send_student_credentials_email.delay(user.id, password=DEFAULT_STUDENT_PASSWORD)
    except AdmittedStudent.DoesNotExist:
        logger.error("provision_student_portal_account_sync: admission %s not found", admission_id)
    except Exception:
        logger.exception(
            "Synchronous student portal provisioning failed for admission %s",
            admission_id,
        )


def trigger_background_tasks(admission_id, application_id):
    provision_student_portal_account_sync(admission_id)
    celery_admission_email.delay(application_id, admission_id)
    celery_create_student_account.delay(admission_id, application_id)
