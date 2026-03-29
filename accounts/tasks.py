from celery import shared_task
from django.apps import apps
from .utils.emails import send_account_email, send_reset_password_link

@shared_task
def celery_send_account_email(user_id, password):
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_account_email(user, password, subject = "Account Created Successfully")

@shared_task
def celery_send_password_reset_Link(user_id):
   User = apps.get_model('accounts', 'User')
   user = User.objects.get(id=user_id)
   send_reset_password_link(user)