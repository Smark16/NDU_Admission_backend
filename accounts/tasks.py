from celery import shared_task
from django.apps import apps
from .utils.emails import send_account_email, send_reset_password_link, send_horizon_reset_password_link

@shared_task
def celery_send_account_email(user_id, password, use_erp_portal=None):
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_account_email(
       user,
       password,
       subject="Account Created Successfully",
       use_erp_portal=use_erp_portal,
   )

@shared_task
def celery_send_password_reset_Link(user_id):
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_reset_password_link(user)

@shared_task
def celery_send_erp_password_reset_Link(user_id):
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_horizon_reset_password_link(user)

@shared_task
def celery_send_reminder_email(user_id):
   from .utils.emails import send_application_reminder
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_application_reminder(user)