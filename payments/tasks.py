from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from payments.models import ApplicationPayment

from payments.utils.Transaction_sync import (
    fetch_transactions_by_range, reconcile_transactions
)

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    expired_time = timezone.now() - timedelta(minutes=10)

    updated_count = ApplicationPayment.objects.filter(
        status='PENDING',
        created_at__lt=expired_time
    ).update(status='FAILED')

    return f"{updated_count} payments marked as FAILED"

# delete failed payments
@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_delete_failed_payments(self):
    expired_time = timezone.now() - timedelta(minutes=10)

    updated_count = ApplicationPayment.objects.filter(
        status='FAILED',
        created_at__lt=expired_time
    ).delete()

    return f"{updated_count} payments have been deleted"

# sync payments from schoolpay
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=10,
    retry_kwargs={"max_retries": 5},
)
def celery_sync_schoolpay_transactions(self):
    today = timezone.now().date()

    from_date = (
        today - timedelta(days=3)
    ).strftime("%Y-%m-%d")

    to_date = today.strftime("%Y-%m-%d")

    data = fetch_transactions_by_range(
        from_date=from_date,
        to_date=to_date
    )

    total_synced = reconcile_transactions(data)

    return (
        f"{total_synced} transaction(s) synced"
    )