from celery import shared_task
from django.apps import apps
from .utils.emails import offerletter_email

@shared_task
def send_offerletter_email(application_id):
    Application = apps.get_model('admissions', 'Application')
    application = Application.objects.get(id=application_id)

    offerletter_email(application)