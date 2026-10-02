from celery import shared_task
from django.apps import apps
from django.utils import timezone

from .utils.email import send_application_email, send_admission_email, send_admission_update, send_student_login_credentials, send_rejection_email
from .utils.notification import create_notification
import logging

logger = logging.getLogger(__name__)


@shared_task
def celery_send_application_email(application_id):
    Application = apps.get_model('admissions', 'Application')
    application = Application.objects.get(id=application_id)

    send_application_email(application)

@shared_task
def celery_application_notification(user_id, title, msg):
    User = apps.get_model('accounts', 'User')
    user = User.objects.get(id=user_id)

    create_notification(user, title, msg)

@shared_task
def celery_send_rejection_email(application_id, msg):
    Application = apps.get_model('admissions', 'Application')
    application = Application.objects.get(id=application_id)

    send_rejection_email(application, msg)
    
@shared_task(bind=True, max_retries=5)
def celery_send_student_credentials_email(self, user_id, password):
    User = apps.get_model('accounts', 'User')
    user = User.objects.get(id=user_id)

    send_student_login_credentials(user, password)

@shared_task(bind=True, max_retries=5)
def celery_admission_email(self, application_id, admission_id):
    Application = apps.get_model('admissions', 'Application')
    Admission = apps.get_model('admissions', 'AdmittedStudent')

    application = Application.objects.get(id=application_id)
    admission = Admission.objects.get(id=admission_id)

    send_admission_email(application, admission)

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def celery_provision_zimbra_on_admission(self, admission_id):
    """Auto-create/link the student's @educ.ndu.ac.ug mailbox on admission
    and notify them (portal bell + personal email, with the setup guide
    link) -- the automatic equivalent of the admin "Provision one student"
    button. Skips quietly if the Zimbra integration isn't configured yet;
    retries on transient request errors, not on permanent config errors."""
    from integrations import zimbra_client, zimbra_provisioning
    from integrations.models import ZimbraIntegrationConfig

    cfg = ZimbraIntegrationConfig.get_solo()
    if not cfg.is_enabled:
        logger.info("Zimbra integration disabled; skipping auto-provisioning for admission %s", admission_id)
        return

    Admission = apps.get_model("admissions", "AdmittedStudent")
    student = (
        Admission.objects.select_related(
            "student_user", "application", "admitted_program", "admitted_batch", "intended_program_batch"
        )
        .filter(pk=admission_id)
        .first()
    )
    if not student:
        logger.warning("Zimbra auto-provisioning: admission %s not found", admission_id)
        return

    try:
        zimbra_provisioning.provision_student(student, notify=True, channel="both")
    except zimbra_client.ZimbraConfigError as e:
        logger.info("Zimbra not fully configured; skipping auto-provisioning for admission %s: %s", admission_id, e)
    except zimbra_client.ZimbraRequestError as e:
        logger.warning("Zimbra auto-provisioning request error for admission %s: %s", admission_id, e)
        raise self.retry(exc=e)
    except Exception as e:
        logger.exception("Zimbra auto-provisioning unexpected error for admission %s: %s", admission_id, e)

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def celery_send_notify_broadcast_email(self, to_email, subject, body, attachments=None, is_html=False):
    """One recipient's email from the admin "Notify users" broadcast
    (StudentNotifySendView). Queued per-recipient so a large audience
    (hundreds/thousands) can never make that view block long enough to
    hit a gunicorn worker timeout -- see the Zimbra credentials rollout
    incident where a synchronous send of 1435 emails got the worker
    SIGKILLed partway through with no record of who was actually sent.

    attachments: optional list of {filename, mime_type, content_b64}.
    is_html: when True, body is HTML (Gmail-like rich text from Notify users).
    """
    import base64

    from django.utils.html import strip_tags

    from ndu_portal.send_grid import send_configurable_email

    try:
        parsed = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            b64 = item.get("content_b64") or ""
            if not b64:
                continue
            try:
                raw = base64.b64decode(b64)
            except Exception:
                continue
            parsed.append(
                {
                    "content": raw,
                    "filename": item.get("filename") or "attachment",
                    "mime_type": item.get("mime_type") or "application/octet-stream",
                }
            )
        ok = send_configurable_email(
            to_email,
            subject,
            body,
            is_html=bool(is_html),
            plain_text_fallback=strip_tags(body) if is_html else None,
            attachments=parsed or None,
        )
        if not ok:
            raise RuntimeError(f"SendGrid rejected send to {to_email}")
    except Exception as e:
        logger.exception("Notify broadcast email failed for %s: %s", to_email, e)
        raise self.retry(exc=e)

@shared_task
def celery_admission_update(admission_id):
    Admission = apps.get_model('admissions', 'AdmittedStudent')
    admission = Admission.objects.get(id=admission_id)
    send_admission_update(admission, subject="Admission updated Successfully")

@shared_task(bind=True, max_retries=5)
def celery_create_student_account(self, admission_id, application_id):
    """
    Legacy Celery entry point — provisioning is synchronous on admission.

    Re-runs ensure + auto-enroll if a worker retry is needed; credentials email only on create.
    """
    try:
        from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, ensure_student_portal_account
        from admissions.utils.email import send_student_login_credentials
        from admissions.utils.student_portal_provisioning import auto_enroll_admitted_student

        Admission = apps.get_model("admissions", "AdmittedStudent")
        admission = Admission.objects.select_related(
            "application__applicant", "student_user"
        ).get(id=admission_id)

        user, created = ensure_student_portal_account(admission)
        if user is None:
            logger.warning("Student account not provisioned for admission %s", admission_id)
            return

        if created:
            send_student_login_credentials(
                user, DEFAULT_STUDENT_PASSWORD, admission=admission
            )

        auto_enroll_admitted_student(admission, admission.admitted_by_id)

    except Exception as e:
        logger.exception(f"Student account creation failed: {e}")
        raise self.retry(exc=e, countdown=60)

# update student account
@shared_task(bind=True, max_retries=5)
def celery_update_student_account(self, admission_id, application_id):
    try:
        from admissions.student_accounts import ensure_student_portal_account, DEFAULT_STUDENT_PASSWORD

        Admission = apps.get_model('admissions', 'AdmittedStudent')
        admission = Admission.objects.select_related(
            'application__applicant', 'student_user'
        ).get(id=admission_id)

        user, created = ensure_student_portal_account(admission, reset_password=True)
        if user is None:
            logger.warning("Student account update skipped for admission %s", admission_id)
            return

        celery_send_student_credentials_email.delay(
            user.id,
            password=DEFAULT_STUDENT_PASSWORD,
        )

        celery_auto_enroll_students.delay(admission.id, admission.admitted_by_id)

    except Admission.DoesNotExist:
        logger.error(f"AdmittedStudent with id {admission_id} not found")
    except Exception as e:
        logger.exception(f"Student account update failed for admission {admission_id}: {e}")
        raise self.retry(exc=e, countdown=60)

# AutoEnroll Students
def auto_enroll_admitted_student_task(admission_id, user_id):
    """Celery wrapper — prefer admissions.utils.student_portal_provisioning.auto_enroll_admitted_student."""
    from admissions.utils.student_portal_provisioning import auto_enroll_admitted_student

    Admission = apps.get_model("admissions", "AdmittedStudent")
    admission = Admission.objects.get(id=admission_id)
    auto_enroll_admitted_student(admission, user_id)


@shared_task(bind=True, max_retries=5)
def celery_auto_enroll_students(self, admission_id, user_id):
    try:
        auto_enroll_admitted_student_task(admission_id, user_id)
    except Exception as e:
        logger.exception(f"Auto-enrollment failed: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def celery_send_weekly_admissions_digest(triggered_by_user_id=None):
    from admissions.utils.weekly_report import send_weekly_admissions_digest

    return send_weekly_admissions_digest(triggered_by_user_id=triggered_by_user_id)


@shared_task
def celery_maybe_send_weekly_admissions_digest():
    """Hourly check: send digest when schedule matches and not already sent this week."""
    from admissions.models import WeeklyReportSettings
    from admissions.utils.weekly_report import send_weekly_admissions_digest

    settings_row = WeeklyReportSettings.get_solo()
    if not settings_row.is_enabled:
        return {"skipped": "disabled"}

    now = timezone.localtime()
    if now.weekday() != settings_row.schedule_day:
        return {"skipped": "wrong_day"}
    if now.hour != settings_row.schedule_hour:
        return {"skipped": "wrong_hour"}
    if now.minute < settings_row.schedule_minute:
        return {"skipped": "before_minute"}

    if settings_row.last_sent_at:
        days_since = (now.date() - timezone.localtime(settings_row.last_sent_at).date()).days
        if days_since < 6:
            return {"skipped": "already_sent_this_week"}

    return send_weekly_admissions_digest()


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def celery_send_accounts_registration_cleared_email(self, student_id):
    """Background email after Accounts registration clearance (does not block the API)."""
    try:
        Admission = apps.get_model("admissions", "AdmittedStudent")
        student = Admission.objects.select_related(
            "application",
            "admitted_program",
            "admitted_campus",
            "programme_enrollment",
        ).get(pk=student_id)
        if not student.accounts_registration_cleared:
            logger.info(
                "Skip accounts-clearance email: student %s is not cleared",
                student_id,
            )
            return False
        from admissions.utils.email import send_accounts_registration_cleared_email

        ok = send_accounts_registration_cleared_email(student)
        if not ok:
            raise RuntimeError(
                f"Accounts clearance email failed for student {student_id}"
            )
        return True
    except Exception as exc:
        logger.exception(
            "Accounts clearance email task failed for student %s", student_id
        )
        raise self.retry(exc=exc)
