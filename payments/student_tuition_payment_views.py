"""Student portal: initiate tuition via SchoolPay (same Adhoc flow as application fee)."""
from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from payments.models import StudentTuitionPayment
from payments.student_portal_finance import get_admitted_student_for_user
from payments.utils.school_pay_code import register_student_with_schoolpay
from payments.utils.schoolpay import SchoolPayClient

logger = logging.getLogger(__name__)

UG_PHONE_RE = re.compile(r"^(256|0)?(7\d{8})$")


def _normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    m = UG_PHONE_RE.match(digits)
    if not m:
        return ""
    return "256" + m.group(2)


def _student_names(student):
    app = getattr(student, "application", None)
    if app:
        return (app.first_name or "Student").strip(), (app.last_name or "Student").strip()
    user = getattr(student, "student_user", None)
    if user:
        return (user.first_name or "Student").strip(), (user.last_name or "Student").strip()
    return "Student", "Student"


def _webhook_callback_url(request) -> str:
    if settings.DEBUG and getattr(settings, "SCHOOLPAY_WEBHOOK_URL", None):
        return settings.SCHOOLPAY_WEBHOOK_URL.rstrip("/") + "/"
    return request.build_absolute_uri("/api/payments/webhook/")


def _api_status(payment: StudentTuitionPayment) -> str:
    if payment.status == "completed":
        return "PAID"
    if payment.status in ("failed", "cancelled"):
        return payment.status.upper()
    return "PENDING"


class InitiateTuitionPaymentView(APIView):
    """
    POST /api/payments/student/initiate_tuition_payment
    Body: { phone, amount, first_name?, last_name? }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        phone = _normalize_phone(request.data.get("phone", ""))
        if not phone:
            return Response(
                {"detail": "Valid Uganda mobile money number required (e.g. 0771234567)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            amount = Decimal(str(request.data.get("amount")))
        except (InvalidOperation, TypeError):
            return Response(
                {"detail": "amount must be a valid number."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if amount <= 0:
            return Response(
                {"detail": "amount must be greater than zero."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not student.is_registered_with_schoolpay or not student.student_id:
            reg = register_student_with_schoolpay(student)
            if not reg.get("success"):
                return Response(
                    {
                        "detail": (
                            "Could not register your SchoolPay payment profile. "
                            f"{reg.get('error', 'Contact finance office.')}"
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            student.refresh_from_db()

        first_name, last_name = _student_names(student)
        if request.data.get("first_name"):
            first_name = str(request.data["first_name"]).strip() or first_name
        if request.data.get("last_name"):
            last_name = str(request.data["last_name"]).strip() or last_name

        # Reconcile this student's stale pendings with SchoolPay before blocking retry.
        from payments.utils.tuition_payment_status import (
            reconcile_stale_pending_tuition_payments,
        )

        reconcile_stale_pending_tuition_payments(
            StudentTuitionPayment.objects.filter(student=student),
            stale_minutes=10,
        )

        if StudentTuitionPayment.objects.filter(student=student, status="pending").exists():
            return Response(
                {"detail": "You already have a pending tuition payment. Wait or try again in a few minutes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ext_ref = f"TUI-{uuid.uuid4().hex.upper()}"
        reason = f"Tuition — {student.student_id}"

        try:
            client = SchoolPayClient()
            response_data = client.request_payment(
                amount=float(amount),
                phone=phone,
                ext_ref=ext_ref,
                first_name=first_name,
                last_name=last_name,
                reason=reason,
                callBackUrl=_webhook_callback_url(request),
            )
        except ValueError as e:
            logger.exception("SchoolPay tuition initiate failed for student %s", student.pk)
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        if response_data.get("returnCode") != 0:
            return Response(
                {"detail": response_data.get("returnMessage") or "SchoolPay rejected the payment request."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment_reference = response_data.get("paymentReference")
        if not payment_reference:
            return Response(
                {"detail": "SchoolPay did not return a payment reference."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        payment = StudentTuitionPayment.objects.create(
            student=student,
            source="scheduled",
            amount=amount,
            currency="UGX",
            payment_method="mobile_money",
            status="pending",
            payment_reference=payment_reference,
            transaction_id=ext_ref,
            notes=f"Portal tuition payment. externalReference={ext_ref}. payment_code={student.student_id}",
        )

        return Response(
            {
                "payment_reference": payment_reference,
                "external_reference": ext_ref,
                "status": "PENDING",
                "payment_code": student.student_id,
            },
            status=status.HTTP_201_CREATED,
        )


class TuitionPaymentStatusView(APIView):
    """
    GET /api/payments/student/tuition_payment_status/<payment_ref>
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, payment_ref):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payment = (
            StudentTuitionPayment.objects.filter(
                student=student,
                payment_reference=payment_ref,
            )
            .first()
        )
        if not payment:
            return Response({"detail": "Payment not found."}, status=status.HTTP_404_NOT_FOUND)

        if payment.status == "completed":
            return Response(
                {
                    "status": "PAID",
                    "receipt_number": payment.receipt_number or "",
                    "transaction_id": payment.transaction_id or "",
                }
            )

        from payments.utils.tuition_payment_status import reconcile_pending_tuition_payment

        try:
            reconcile_pending_tuition_payment(payment)
        except Exception:
            logger.exception(
                "Tuition status reconcile failed for ref %s", payment_ref
            )

        payment.refresh_from_db()
        return Response(
            {
                "status": _api_status(payment),
                "receipt_number": payment.receipt_number or "",
                "transaction_id": payment.transaction_id or "",
            }
        )
