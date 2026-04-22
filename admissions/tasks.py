from celery import shared_task
from django.apps import apps

from .utils.email import send_application_email, send_admission_email, send_admission_update, send_rejection_email
from .utils.notification import create_notification
from ndu_portal.send_grid import send_configurable_email


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

@shared_task
def celery_rejection_email(application_id, rejection_reason):
    Application = apps.get_model('admissions', 'Application')
    application = Application.objects.get(id=application_id)

    send_rejection_email(application, rejection_reason=rejection_reason)


@shared_task
def celery_bulk_announcement(application_ids, subject, body):
    Application = apps.get_model('admissions', 'Application')
    applications = Application.objects.filter(id__in=application_ids).only('first_name', 'last_name', 'email')
    sent = 0
    failed = 0
    for app in applications:
        personalised = body.replace("{first_name}", app.first_name).replace("{last_name}", app.last_name)
        try:
            send_configurable_email(app.email, subject, personalised)
            sent += 1
        except Exception:
            failed += 1
    return {"sent": sent, "failed": failed}