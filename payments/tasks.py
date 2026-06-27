from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from payments.models import ApplicationPayment

from payments.utils.Transaction_sync import (
    fetch_transactions_by_range, reconcile_transactions
)
from payments.utils.application_payment_status import (
    reconcile_stale_pending_application_payments,
)

import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    """
    Reconcile stale PENDING application-fee payments with SchoolPay.
    Does not mark FAILED unless the gateway confirms failure.
    """
    results = reconcile_stale_pending_application_payments()
    return (
        f"{results['paid']} paid, {results['failed']} failed, "
        f"{results['still_pending']} still pending, {results['errors']} errors"
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_delete_failed_payments(self):
    """
    Disabled: failed application payments are kept for finance reconciliation.
    """
    logger.info(
        "auto_delete_failed_payments skipped (retention enabled for reconciliation)"
    )
    return "0 payments deleted (task disabled)"


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
