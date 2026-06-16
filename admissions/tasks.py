from celery import shared_task
from django.apps import apps
from django.utils import timezone
from payments.models import RegistrationSettings
from Programs.models import StudentProgrammeEnrollment
from Programs.program_batch_resolution import resolve_default_program_batch_for_program

from .utils.email import send_application_email, send_admission_email, send_admission_update, send_student_login_credentials, send_rejection_email
from .utils.notification import create_notification
from django.db import transaction
from accounts.models import User
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

@shared_task
def celery_admission_update(admission_id):
    Admission = apps.get_model('admissions', 'AdmittedStudent')
    admission = Admission.objects.get(id=admission_id)
    send_admission_update(admission, subject="Admission updated Successfully")

@shared_task(bind=True, max_retries=5)
def celery_create_student_account(self, admission_id, application_id):
    try:
        from admissions.student_accounts import ensure_student_portal_account, DEFAULT_STUDENT_PASSWORD

        Admission = apps.get_model('admissions', 'AdmittedStudent')
        admission = Admission.objects.select_related(
            'application__applicant', 'student_user'
        ).get(id=admission_id)

        user, created = ensure_student_portal_account(admission)
        if user is None:
            logger.warning("Student account not provisioned for admission %s", admission_id)
            return

        if created:
            celery_send_student_credentials_email.delay(
                user.id,
                password=DEFAULT_STUDENT_PASSWORD,
            )

        celery_auto_enroll_students.delay(
            admission.id,
            admission.admitted_by_id,
        )

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
@shared_task(bind=True, max_retries=5)
def celery_auto_enroll_students(self, admission_id, user_id):
    Admission = apps.get_model('admissions', 'AdmittedStudent')
    User = apps.get_model('accounts', 'User')

    admission = Admission.objects.get(id=admission_id)
    user = User.objects.get(id=user_id)
    try:
        reg_settings = RegistrationSettings.get_settings()

        today = timezone.now().date()
        program_batch = admission.intended_program_batch or resolve_default_program_batch_for_program(
            admission.admitted_program,
            today=today,
            admission_batch=admission.admitted_batch,
        )

        if program_batch:
            StudentProgrammeEnrollment.objects.get_or_create(
                student=admission,
                defaults={
                    'program': admission.admitted_program,
                    'program_batch': program_batch,
                    'current_year_of_study': 1,
                    'current_term_number': 1,
                    'status': "enrolled" if reg_settings.auto_enroll_on_admission else "pending",
                    'enrolled_by': user if reg_settings.auto_enroll_on_admission else None,
                    'enrolled_at': timezone.now() if reg_settings.auto_enroll_on_admission else None,
                }
        )
    except Exception as e:
        logger.exception(f"Auto-enrollment failed: {e}")
