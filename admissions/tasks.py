from celery import shared_task
from django.apps import apps

from .utils.email import send_application_email, send_admission_email, send_admission_update
from .utils.notification import create_notification


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
def celery_admission_email(application_id, admission_id):
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