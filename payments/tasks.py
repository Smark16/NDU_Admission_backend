from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from payments.models import ApplicationPayment


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    expired_time = timezone.now() - timedelta(minutes=5)

    updated_count = ApplicationPayment.objects.filter(
        status='PENDING',
        created_at__lt=expired_time
    ).update(status='FAILED')

    return f"{updated_count} payments marked as FAILED"