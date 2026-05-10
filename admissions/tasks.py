from celery import shared_task
from django.apps import apps
from django.utils import timezone
from payments.models import RegistrationSettings
from Programs.models import StudentProgrammeEnrollment, ProgramBatch

from .utils.email import send_application_email, send_admission_email, send_admission_update, send_student_login_credentials
from .utils.notification import create_notification
from django.db import transaction
# from django.db import close_old_connections
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
        Admission = apps.get_model('admissions', 'AdmittedStudent')
        Application = apps.get_model('admissions', 'Application')

        admission = Admission.objects.get(id=admission_id)
        application = Application.objects.get(id=application_id)

        if admission.student_user_id:
                return

        student_username = str(admission.reg_no).strip()
      
        student_user, created = User.objects.get_or_create(
                username=student_username,
                defaults={
                    'first_name': application.applicant.first_name or "",
                    'last_name': application.applicant.last_name or "",
                    'email': application.applicant.email,
                    'is_student': True,
                    'must_change_password': True,
                        }
                    )
        if created:
                student_user.set_password('NDU@1234')
                student_user.save()

                celery_send_student_credentials_email.delay(
                    student_user.id,
                    password='NDU@1234'
                )

        admission.student_user = student_user
        admission.save(update_fields=['student_user'])

        celery_auto_enroll_students.delay(
            admission.id,
            admission.admitted_by_id
        )

    except Exception as e:
        logger.exception(f"Student account creation failed: {e }")

# AutoEnroll Students
@shared_task(bind=True, max_retries=5)
def celery_auto_enroll_students(self, admission_id, user_id):
    Admission = apps.get_model('admissions', 'AdmittedStudent')
    User = apps.get_model('accounts', 'User')

    admission = Admission.objects.get(id=admission_id)
    user = User.objects.get(id=user_id)
    try:
        reg_settings = RegistrationSettings.get_settings()

        # Get or create ProgramBatch
        program_batch = ProgramBatch.objects.filter(
            program=admission.admitted_program
        ).order_by('-is_active', '-start_date').first()

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
