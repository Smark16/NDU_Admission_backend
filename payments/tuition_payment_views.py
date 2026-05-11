"""
Student portal: initiate and poll tuition payments via SchoolPay.

Endpoints
---------
POST /api/payments/student/initiate_tuition_payment
    Body: { phone, amount }
    • generates ext_ref  = TUT-{reg_no}-{8-char uuid}
    • calls SchoolPayClient.request_payment()
    • creates StudentTuitionPayment(source='ad_hoc', status='pending')
    • returns { payment_reference, external_reference, amount, status }

GET  /api/payments/student/tuition_payment_status/<payment_ref>
    • checks SchoolPay (or local record if already COMPLETED)
    • updates StudentTuitionPayment on PAID
    • returns { status, receipt_number }

Design notes
------------
• reg_no is used as the stable "SchoolPay ID" displayed to students so they
  can pay outside the portal at any SchoolPay agent using their reg_no.
• ext_ref for portal-initiated payments embeds the reg_no so staff can
  reconcile outside payments by looking at the reference prefix.
• Webhook handling (for outside-portal or async confirmation) is in views.py.
"""
from __future__ import annotations

import uuid
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import StudentTuitionPayment
from .student_portal_finance import get_admitted_student_for_user
from .utils.schoolpay import SchoolPayClient

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────

def _callback_url(request) -> str:
    """Build absolute webhook URL from the current request host."""
    return request.build_absolute_uri('/api/payments/webhook/')


def _student_payment_phone(student, phone: str) -> str:
    phone = (phone or "").strip()
    if phone:
        return phone
    try:
        return (student.application.phone or "").strip()
    except Exception:
        return ""


def _student_payment_name(student) -> tuple[str, str]:
    first_name = ""
    last_name = ""
    try:
        app = student.application
        first_name = app.first_name or ""
        last_name = app.last_name or ""
    except Exception:
        first_name = student.reg_no
    return first_name, last_name


def _initiate_student_tuition_payment(student, request, *, phone: str, amount, reason: str):
    try:
        amount_decimal = float(amount)
        if amount_decimal <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return None, Response(
            {"detail": "amount must be a positive number."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    phone = _student_payment_phone(student, phone)
    if not phone:
        return None, Response(
            {"detail": "phone is required (or set on your application profile)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from datetime import timedelta

    StudentTuitionPayment.objects.filter(
        student=student,
        source="ad_hoc",
        status="pending",
        created_at__lt=timezone.now() - timedelta(minutes=15),
    ).update(status="cancelled")

    existing = StudentTuitionPayment.objects.filter(
        student=student,
        source="ad_hoc",
        status="pending",
    ).first()
    if existing:
        return None, Response(
            {
                "detail": "You already have a pending payment. Wait for it to complete or expire.",
                "payment_reference": existing.payment_reference,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    pay_id = student.effective_schoolpay_code
    ext_ref = f"TUT-{pay_id}-{uuid.uuid4().hex[:8].upper()}"
    first_name, last_name = _student_payment_name(student)

    client = SchoolPayClient()
    try:
        resp = client.request_payment(
            amount=amount_decimal,
            phone=phone,
            ext_ref=ext_ref,
            first_name=first_name,
            last_name=last_name,
            reason=reason,
            callBackUrl=_callback_url(request),
        )
    except ValueError as exc:
        logger.error("SchoolPay tuition initiation failed: %s", exc)
        return None, Response(
            {"detail": "Payment gateway error. Please try again."},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if resp.get("returnCode") != 0:
        return None, Response(
            {"detail": resp.get("returnMessage", "Payment initiation failed.")},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payment = StudentTuitionPayment.objects.create(
        student=student,
        source="ad_hoc",
        label=f"{reason} — portal initiated ({student.reg_no})",
        amount=amount_decimal,
        currency="UGX",
        payment_method="mobile_money",
        status="pending",
        payment_reference=resp.get("paymentReference"),
        transaction_id=ext_ref,
        charged_by=None,
    )
    return payment, None


# ── views ──────────────────────────────────────────────────────────────────

class InitiateTuitionPayment(APIView):
    """
    POST /api/payments/student/initiate_tuition_payment
    Body: { phone: str, amount: number }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "No admitted student record found for this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        phone = request.data.get("phone")
        amount = request.data.get("amount")
        if not amount:
            return Response({"detail": "amount is required."}, status=status.HTTP_400_BAD_REQUEST)

        payment, error = _initiate_student_tuition_payment(
            student,
            request,
            phone=phone,
            amount=amount,
            reason="Tuition Payment",
        )
        if error is not None:
            return error

        return Response({
            "payment_reference": payment.payment_reference,
            "external_reference": payment.transaction_id,
            "amount": float(payment.amount),
            "currency": "UGX",
            "status": payment.status,
        })


class GenerateTuitionReference(APIView):
    """
    POST /api/payments/student/generate_tuition_reference
    Body: { amount: number, phone?: str }
    Creates a SchoolPay PRN for agent or bank payment without opening the pay modal.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "No admitted student record found for this account."},
                status=status.HTTP_404_NOT_FOUND,
            )

        amount = request.data.get("amount")
        if not amount:
            return Response({"detail": "amount is required."}, status=status.HTTP_400_BAD_REQUEST)

        payment, error = _initiate_student_tuition_payment(
            student,
            request,
            phone=request.data.get("phone"),
            amount=amount,
            reason="Tuition Payment",
        )
        if error is not None:
            return error

        return Response({
            "payment_reference": payment.payment_reference,
            "external_reference": payment.transaction_id,
            "amount": float(payment.amount),
            "currency": "UGX",
            "status": payment.status,
        })


class CheckTuitionPaymentStatus(APIView):
    """
    GET /api/payments/student/tuition_payment_status/<payment_ref>
    Polls SchoolPay and updates the StudentTuitionPayment record.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, payment_ref):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "No admitted student record found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            payment = StudentTuitionPayment.objects.get(
                payment_reference=payment_ref,
                student=student,
            )
        except StudentTuitionPayment.DoesNotExist:
            return Response({"detail": "Payment record not found."}, status=status.HTTP_404_NOT_FOUND)

        # Already settled — return immediately
        if payment.status == "completed":
            return Response({
                "status": "PAID",
                "receipt_number": payment.receipt_number or "",
            })
        if payment.status in ("cancelled", "failed"):
            return Response({"status": payment.status.upper()})

        # Poll SchoolPay
        client = SchoolPayClient()
        try:
            data = client.check_status(payment.payment_reference)
        except ValueError as exc:
            logger.error("SchoolPay tuition status check failed: %s", exc)
            return Response({"status": payment.status.upper()})

        if data.get("returnCode") == 0:
            sp_status = data.get("status", "")
            if sp_status == "PAID":
                with transaction.atomic():
                    payment.status = "completed"
                    payment.receipt_number = data.get("receiptNumber", "")
                    payment.paid_at = timezone.now()
                    # keep transaction_id as the ext_ref stored earlier;
                    # store SchoolPay's transactionId in notes to avoid overwrite
                    payment.notes = (
                        payment.notes + f"\nSchoolPay transactionId: {data.get('transactionId', '')}"
                    ).strip()
                    payment.save()
            elif sp_status in ("FAILED", "CANCELLED"):
                payment.status = "failed"
                payment.save()

        public_status = "PAID" if payment.status == "completed" else payment.status.upper()
        return Response({
            "status": public_status,
            "receipt_number": payment.receipt_number or "",
        })