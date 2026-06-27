"""Staff tools: application-fee payment exception queues and reconciliation actions."""
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.erp_drf_permissions import FinanceModuleAdminPermission
from admissions.models import Application
from payments.models import ApplicationPayment
from payments.utils.application_payment_status import (
    mark_application_payment_paid,
    reconcile_pending_application_payment,
    sync_draft_and_application_on_paid,
)


def _applicant_name(user):
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return name or user.email or user.username


def _serialize_payment(payment: ApplicationPayment, *, stale=False):
    age_minutes = None
    if payment.created_at:
        age_minutes = int((timezone.now() - payment.created_at).total_seconds() // 60)

    application = payment.application
    batch_name = None
    if application and application.batch_id:
        batch_name = application.batch.name
    elif not application:
        draft = payment.user.drafts.order_by("-updated_at").first()
        if draft and draft.batch_id:
            batch_name = draft.batch.name

    return {
        "id": payment.id,
        "applicant_name": _applicant_name(payment.user),
        "applicant_email": payment.user.email,
        "phone_number": payment.phone_number,
        "amount": str(payment.amount),
        "status": payment.status,
        "external_reference": payment.external_reference,
        "payment_reference": payment.payment_reference,
        "receipt_number": payment.receipt_number,
        "transaction_id": payment.transaction_id,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "age_minutes": age_minutes,
        "is_stale_pending": stale,
        "application_id": application.id if application else None,
        "application_status": application.status if application else None,
        "batch_name": batch_name,
    }


def _serialize_unpaid_application(application: Application):
    paid_payment = ApplicationPayment.objects.filter(
        user=application.applicant,
        status="PAID",
    ).order_by("-updated_at").first()

    return {
        "application_id": application.id,
        "applicant_name": f"{application.first_name} {application.last_name}".strip(),
        "applicant_email": application.email or application.applicant.email,
        "batch_name": application.batch.name if application.batch_id else None,
        "application_reference": application.application_reference,
        "status": application.status,
        "submitted_at": application.created_at.isoformat()
        if application.created_at
        else None,
        "has_paid_payment_record": paid_payment is not None,
        "paid_payment_id": paid_payment.id if paid_payment else None,
    }


class ApplicationFeeExceptionsView(APIView):
    """List stuck pending, failed, and unpaid-submitted application-fee cases."""

    permission_classes = [IsAuthenticated, FinanceModuleAdminPermission]

    def get(self, request):
        stale_cutoff = timezone.now() - timedelta(minutes=10)
        failed_cutoff = timezone.now() - timedelta(days=30)

        stale_qs = ApplicationPayment.objects.filter(
            status="PENDING",
            created_at__lt=stale_cutoff,
        )
        failed_qs = ApplicationPayment.objects.filter(
            status="FAILED",
            created_at__gte=failed_cutoff,
        )
        unpaid_qs = Application.objects.filter(
            application_fee_paid=False,
            status__in=["submitted", "under_review", "accepted"],
        )

        stale_pending = (
            stale_qs.select_related("user", "application", "application__batch")
            .order_by("created_at")[:100]
        )
        failed_payments = (
            failed_qs.select_related("user", "application", "application__batch")
            .order_by("-created_at")[:100]
        )
        unpaid_submissions = (
            unpaid_qs.select_related("applicant", "batch")
            .order_by("-id")[:100]
        )

        return Response(
            {
                "counts": {
                    "stale_pending": stale_qs.count(),
                    "failed": failed_qs.count(),
                    "unpaid_submissions": unpaid_qs.count(),
                },
                "stale_pending": [
                    _serialize_payment(p, stale=True) for p in stale_pending
                ],
                "failed_payments": [_serialize_payment(p) for p in failed_payments],
                "unpaid_submissions": [
                    _serialize_unpaid_application(a) for a in unpaid_submissions
                ],
            }
        )


class VerifyApplicationFeePaymentView(APIView):
    """Poll SchoolPay for one application-fee payment."""

    permission_classes = [IsAuthenticated, FinanceModuleAdminPermission]

    def post(self, request, payment_id):
        payment = ApplicationPayment.objects.filter(pk=payment_id).first()
        if not payment:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        outcome = reconcile_pending_application_payment(payment)
        payment.refresh_from_db()

        return Response(
            {
                "detail": f"Verification complete: {outcome}",
                "outcome": outcome,
                "payment": _serialize_payment(
                    payment,
                    stale=payment.status == "PENDING"
                    and payment.created_at
                    and payment.created_at < timezone.now() - timedelta(minutes=10),
                ),
            }
        )


class ReconcileApplicationFeePaymentView(APIView):
    """Manually mark an application-fee payment PAID (staff-entered receipt)."""

    permission_classes = [IsAuthenticated, FinanceModuleAdminPermission]

    def post(self, request, payment_id):
        payment = ApplicationPayment.objects.filter(pk=payment_id).first()
        if not payment:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        receipt_number = (request.data.get("receipt_number") or "").strip()
        transaction_id = (request.data.get("transaction_id") or "").strip()

        if not receipt_number:
            return Response(
                {"detail": "receipt_number is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mark_application_payment_paid(
            payment,
            receipt_number=receipt_number,
            transaction_id=transaction_id or None,
        )
        payment.refresh_from_db()

        return Response(
            {
                "detail": "Payment marked as reconciled.",
                "payment": _serialize_payment(payment),
                "reconciled_by": request.user.email,
            }
        )


class SyncUnpaidApplicationFeeView(APIView):
    """Try to heal a submitted application from an existing PAID payment record."""

    permission_classes = [IsAuthenticated, FinanceModuleAdminPermission]

    def post(self, request, application_id):
        application = Application.objects.filter(pk=application_id).select_related(
            "applicant"
        ).first()
        if not application:
            return Response(
                {"detail": "Application not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payment = None
        if application.application_reference:
            payment = ApplicationPayment.objects.filter(
                user=application.applicant,
                external_reference=application.application_reference,
                status="PAID",
            ).first()

        if payment is None:
            payment = (
                ApplicationPayment.objects.filter(
                    user=application.applicant,
                    status="PAID",
                    application__isnull=True,
                )
                .order_by("-updated_at")
                .first()
            )

        if payment is None:
            payment = (
                ApplicationPayment.objects.filter(
                    user=application.applicant,
                    status="PAID",
                )
                .order_by("-updated_at")
                .first()
            )

        if payment is None:
            return Response(
                {
                    "detail": "No PAID application-fee payment found for this applicant.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        sync_draft_and_application_on_paid(payment)
        payment.application = application
        payment.save(update_fields=["application"])

        application.refresh_from_db()
        return Response(
            {
                "detail": "Application fee status synced from payment record.",
                "application_id": application.id,
                "application_fee_paid": application.application_fee_paid,
                "payment_id": payment.id,
            }
        )
