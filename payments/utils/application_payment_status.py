"""
Shared helpers for application-fee payment status (SchoolPay → ApplicationPayment → draft/application).
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from admissions.models import Application
from Drafts.models import DraftApplication
from payments.models import ApplicationPayment
from payments.utils.schoolpay import SchoolPayClient

logger = logging.getLogger(__name__)

GATEWAY_FAILED_STATUSES = frozenset({"FAILED", "CANCELLED"})

SUBMITTED_APPLICATION_STATUSES = frozenset(
    {"submitted", "under_review", "accepted", "Admitted", "admitted"}
)


def _normalize_payment_reference(value):
    if value in (None, ""):
        return None
    ref = str(value).strip()
    return ref or None


def confirmed_application_fee_payment(applicant_user, *, external_reference=None, draft=None):
    """
    Return a PAID application-fee payment that may be used for submit.

    Ignores draft.application_fee_paid flags — only SchoolPay-confirmed PAID rows count.
    Skips payments already linked to a submitted application.
    """
    refs = set()
    ref = _normalize_payment_reference(external_reference)
    if ref:
        refs.add(ref)
    if draft and draft.application_reference:
        normalized = _normalize_payment_reference(draft.application_reference)
        if normalized:
            refs.add(normalized)

    qs = ApplicationPayment.objects.filter(user=applicant_user, status="PAID")
    if refs:
        qs = qs.filter(external_reference__in=refs)

    for payment in qs.order_by("-created_at"):
        if not payment.application_id:
            return payment
        application = Application.objects.filter(pk=payment.application_id).first()
        if application is None or application.status not in SUBMITTED_APPLICATION_STATUSES:
            return payment
    return None


def schoolpay_application_fee_callback_url(request=None):
    """Public webhook URL for SchoolPay application-fee callbacks."""
    from django.conf import settings

    base = (getattr(settings, "BACKEND_URL", None) or "").strip().rstrip("/")
    if base:
        return f"{base}/api/payments/webhook/"
    if request is not None:
        return request.build_absolute_uri("/api/payments/webhook/")
    return "/api/payments/webhook/"


def sync_draft_and_application_on_paid(payment: ApplicationPayment, draft=None):
    """Propagate PAID status to the applicant draft and any matching application."""
    if draft is None:
        draft = (
            DraftApplication.objects.filter(applicant=payment.user)
            .order_by("-updated_at")
            .first()
        )

    if draft:
        draft.application_fee_paid = True
        draft.application_reference = payment.external_reference
        draft.save(update_fields=["application_fee_paid", "application_reference"])

    application = payment.application
    if application is None:
        application = Application.objects.filter(
            applicant=payment.user,
            application_reference=payment.external_reference,
        ).first()

    app_update_fields = []
    if application:
        if not application.application_fee_paid:
            application.application_fee_paid = True
            app_update_fields.append("application_fee_paid")
        if payment.amount and application.application_fee_amount != payment.amount:
            application.application_fee_amount = payment.amount
            app_update_fields.append("application_fee_amount")
        if not application.application_reference:
            application.application_reference = payment.external_reference
            app_update_fields.append("application_reference")
        if app_update_fields:
            application.save(update_fields=app_update_fields)

    if application and payment.application_id is None:
        payment.application = application
        payment.save(update_fields=["application"])


def mark_application_payment_paid(
    payment: ApplicationPayment,
    *,
    receipt_number=None,
    transaction_id=None,
    draft=None,
):
    """Idempotently mark an ApplicationPayment PAID and sync draft/application."""
    update_fields = []
    if payment.status != "PAID":
        payment.status = "PAID"
        update_fields.append("status")
    if receipt_number and payment.receipt_number != receipt_number:
        payment.receipt_number = receipt_number
        update_fields.append("receipt_number")
    if transaction_id and payment.transaction_id != transaction_id:
        payment.transaction_id = transaction_id
        update_fields.append("transaction_id")
    if update_fields:
        payment.save(update_fields=update_fields)

    sync_draft_and_application_on_paid(payment, draft=draft)
    return payment


def reconcile_pending_application_payment(payment: ApplicationPayment, client=None):
    """
    Poll SchoolPay for one PENDING payment.
    Returns: 'paid' | 'failed' | 'pending' | 'error'
    """
    if not payment.payment_reference:
        logger.warning(
            "ApplicationPayment %s has no payment_reference; cannot reconcile",
            payment.pk,
        )
        return "error"

    if client is None:
        client = SchoolPayClient()

    try:
        data = client.check_status(payment.payment_reference)
    except Exception:
        logger.exception(
            "SchoolPay status check failed for payment %s",
            payment.payment_reference,
        )
        return "error"

    if data.get("returnCode") != 0:
        return "pending"

    gateway_status = (data.get("status") or "").upper()
    if gateway_status == "PAID":
        with transaction.atomic():
            locked = (
                ApplicationPayment.objects.select_for_update()
                .filter(pk=payment.pk)
                .first()
            )
            if locked:
                if locked.status != "PAID":
                    mark_application_payment_paid(
                        locked,
                        receipt_number=data.get("receiptNumber"),
                        transaction_id=data.get("transactionId"),
                    )
                else:
                    sync_draft_and_application_on_paid(locked)
        return "paid"

    if gateway_status in GATEWAY_FAILED_STATUSES:
        payment.status = "FAILED"
        payment.save(update_fields=["status"])
        return "failed"

    return "pending"


def reconcile_stale_pending_application_payments(
    queryset=None,
    *,
    stale_minutes=10,
    client=None,
):
    """
    For PENDING payments older than stale_minutes:
    1. Poll SchoolPay — mark PAID if money was received.
    2. Mark FAILED if the gateway reports FAILED/CANCELLED.
    3. Otherwise auto-abandon (mark FAILED locally) so the applicant can retry.
       Covers initiations where the applicant never entered their Mobile Money PIN.
    """
    cutoff = timezone.now() - timedelta(minutes=stale_minutes)
    qs = queryset
    if qs is None:
        qs = ApplicationPayment.objects.filter(
            status="PENDING",
            created_at__lt=cutoff,
        )
    else:
        qs = qs.filter(status="PENDING", created_at__lt=cutoff)

    if client is None:
        client = SchoolPayClient()

    results = {"paid": 0, "failed": 0, "cleared": 0, "still_pending": 0, "errors": 0}

    for payment in qs.iterator():
        outcome = reconcile_pending_application_payment(payment, client=client)
        payment.refresh_from_db()

        if outcome == "paid" or payment.status == "PAID":
            results["paid"] += 1
            continue
        if outcome == "failed" or payment.status == "FAILED":
            results["failed"] += 1
            continue

        if payment.status != "PENDING":
            continue

        # Gateway still pending, API error, or unverifiable — abandon after stale window.
        abandon_outcome, _ = clear_pending_application_payment(
            payment,
            verify_first=False,
        )
        payment.refresh_from_db()
        if abandon_outcome == "cleared":
            results["cleared"] += 1
        elif abandon_outcome == "paid":
            results["paid"] += 1
        elif abandon_outcome == "error":
            results["errors"] += 1
        else:
            results["still_pending"] += 1

    return results


def clear_pending_application_payment(payment: ApplicationPayment, *, verify_first=True):
    """
    Abandon a stale PENDING payment so the applicant can retry.
    Verifies with SchoolPay first — will not clear if gateway reports PAID.

    Returns: ('paid' | 'cleared' | 'not_pending' | 'error', payment)
    """
    payment.refresh_from_db()
    if payment.status != "PENDING":
        return "not_pending", payment

    if verify_first:
        outcome = reconcile_pending_application_payment(payment)
        payment.refresh_from_db()
        if outcome == "paid":
            return "paid", payment
        if outcome == "error":
            return "error", payment

    if payment.status == "PENDING":
        payment.status = "FAILED"
        payment.save(update_fields=["status"])

    return "cleared", payment
