"""SchoolPay phone prompt for the UGX 50k exemption application form fee.

Unlike paying via SchoolPay student code (general ledger / FIFO allocation),
this uses AdhocPayments Request so the exact amount is tied to the EXEMPTION_FORM
ad-hoc charge and marked completed on webhook / status poll.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.exemption_services import (
    EXEMPTION_FORM_FEE_CODE,
    EXEMPTION_FORM_FEE_UGX,
    ensure_exemption_form_fee_access,
    exemption_form_fee_status,
    exemption_ineligibility,
    form_fee_paid_for_charge,
    exemption_form_fee_settled_by_prompt,
    _ensure_form_fee_charge,
    _form_fee_status_dict,
)
from payments.adhoc_payment_reasons import schoolpay_adhoc_reason
from admissions.models import AdmissionChangeRequest
from payments.models import StudentTuitionPayment
from payments.student_portal_finance import get_admitted_student_for_user
from payments.student_tuition_payment_views import (
    _normalize_phone,
    _student_names,
    _webhook_callback_url,
)
from payments.utils.school_pay_code import register_student_with_schoolpay
from payments.utils.schoolpay import SchoolPayClient
from payments.utils.tuition_payment_status import (
    mark_tuition_payment_completed,
    reconcile_pending_tuition_payment,
)

logger = logging.getLogger(__name__)

STALE_STK_MINUTES = 10


def is_exemption_form_fee_charge(payment: StudentTuitionPayment) -> bool:
    code = getattr(getattr(payment, "fee_head", None), "code", None)
    if code:
        return code == EXEMPTION_FORM_FEE_CODE
    if payment.fee_head_id:
        from payments.models import FeeHead

        return FeeHead.objects.filter(
            pk=payment.fee_head_id, code=EXEMPTION_FORM_FEE_CODE
        ).exists()
    return False


def clear_exemption_form_stk_attempt(payment: StudentTuitionPayment) -> None:
    """Drop an abandoned/failed STK attempt but keep the 50k bill open."""
    StudentTuitionPayment.objects.filter(pk=payment.pk).exclude(status="completed").update(
        status="pending",
        payment_reference="",
        payment_method="",
        transaction_id=None,
        notes=(
            ((payment.notes or "").strip() + "\nSTK attempt cleared for retry.").strip()
        ),
        updated_at=timezone.now(),
    )


def sync_exemption_form_fee_paid_at(payment: StudentTuitionPayment) -> None:
    if payment.status != "completed" or not is_exemption_form_fee_charge(payment):
        return
    paid_at = payment.paid_at or timezone.now()
    # Stamp the linked request and any other open exemption for this student
    # (SchoolPay→tuition mis-allocations often leave form_fee_charge_id unset).
    AdmissionChangeRequest.objects.filter(
        admitted_student_id=payment.student_id,
        change_type="exemption",
        form_fee_paid_at__isnull=True,
    ).filter(
        Q(form_fee_charge_id=payment.pk) | Q(form_fee_charge_id__isnull=True)
    ).update(
        form_fee_paid_at=paid_at,
        form_fee_charge_id=payment.pk,
    )


def manually_complete_exemption_form_fee(payment: StudentTuitionPayment, *, actor=None):
    """
    Mark a pending exemption form-fee charge paid from Django admin.

    Sets a payment_reference so it counts as a real exemption payment (not
    tuition/SchoolPay-code credit). The student page poll will then treat it
    as PAID and can auto-submit if they still have the pay dialog open.
    """
    if not is_exemption_form_fee_charge(payment):
        raise ValueError("This is not an exemption form-fee charge.")
    if payment.status == "completed" and (
        (payment.payment_reference or "").strip() or payment.payment_method == "mobile_money"
    ):
        sync_exemption_form_fee_paid_at(payment)
        return payment

    now = timezone.now()
    ref = (payment.payment_reference or "").strip() or f"ADMIN-{payment.pk}"
    method = (payment.payment_method or "").strip() or "other"
    note = f"Manually completed in Django admin at {now.isoformat()}."
    if actor is not None:
        note = f"{note} By {getattr(actor, 'username', actor)}."
    notes = ((payment.notes or "").strip() + "\n" + note).strip()
    StudentTuitionPayment.objects.filter(pk=payment.pk).update(
        status="completed",
        paid_at=payment.paid_at or now,
        payment_reference=ref,
        payment_method=method,
        verified_by=actor if getattr(actor, "pk", None) else None,
        verified_at=now,
        notes=notes,
    )
    payment.refresh_from_db()
    sync_exemption_form_fee_paid_at(payment)
    return payment


def _api_status(payment: StudentTuitionPayment) -> str:
    if payment.status == "completed":
        return "PAID"
    if payment.status in ("failed", "cancelled"):
        return payment.status.upper()
    return "PENDING"


class InitiateExemptionFormFeePaymentView(APIView):
    """
    POST /api/admissions/change_requests/exemption/form_fee/pay
    Body: { phone }
    Sends SchoolPay MoMo prompt for EXEMPTION_FORM_FEE_UGX.
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
                {
                    "detail": (
                        "Valid Uganda mobile money number required "
                        "(e.g. 0771234567)."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ineligible_code, ineligible_detail = exemption_ineligibility(student)
        if ineligible_code:
            return Response(
                {
                    "detail": ineligible_detail,
                    "code": ineligible_code,
                    "form_fee": exemption_form_fee_status(student),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        charge = _ensure_form_fee_charge(student, charged_by=None)
        if form_fee_paid_for_charge(student, charge):
            access = _form_fee_status_dict(student, charge)
            return Response(
                {
                    "detail": "Exemption form fee is already paid.",
                    "status": "PAID",
                    "form_fee": access,
                }
            )
        if charge.status == "completed" and not exemption_form_fee_settled_by_prompt(charge):
            StudentTuitionPayment.objects.filter(pk=charge.pk).update(
                status="pending",
                paid_at=None,
                payment_method="",
                payment_reference="",
                transaction_id=None,
            )
            charge.refresh_from_db()
            AdmissionChangeRequest.objects.filter(
                change_type="exemption",
                admitted_student=student,
                form_fee_paid_at__isnull=False,
            ).update(form_fee_paid_at=None)

        # Resume / clear a previous STK attempt on this same bill.
        if (charge.payment_reference or "").strip():
            outcome = reconcile_pending_tuition_payment(charge)
            charge.refresh_from_db()
            if outcome == "paid" or charge.status == "completed":
                sync_exemption_form_fee_paid_at(charge)
                return Response(
                    {
                        "detail": "Exemption form fee is already paid.",
                        "status": "PAID",
                        "payment_reference": charge.payment_reference,
                        "form_fee": _form_fee_status_dict(student, charge),
                    }
                )
            if outcome == "failed":
                clear_exemption_form_stk_attempt(charge)
                charge.refresh_from_db()
            elif outcome == "pending":
                age = timezone.now() - (charge.updated_at or charge.created_at)
                force = bool(
                    request.data.get("force")
                    or request.data.get("retry")
                    or request.data.get("cancel_pending")
                )
                if force or age.total_seconds() >= STALE_STK_MINUTES * 60:
                    clear_exemption_form_stk_attempt(charge)
                    charge.refresh_from_db()
                else:
                    return Response(
                        {
                            "detail": (
                                "A payment prompt was already sent. Approve it on "
                                "your phone, or tap Cancel prompt and try again."
                            ),
                            "status": "PENDING",
                            "payment_reference": charge.payment_reference,
                            "form_fee": _form_fee_status_dict(student, charge),
                            "can_cancel": True,
                        },
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
        amount = Decimal(str(EXEMPTION_FORM_FEE_UGX))
        ext_ref = f"EXF-{uuid.uuid4().hex.upper()}"
        reason = schoolpay_adhoc_reason("exemption")

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
            logger.exception(
                "SchoolPay exemption form fee initiate failed for student %s",
                student.pk,
            )
            return Response({"detail": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        if response_data.get("returnCode") != 0:
            return Response(
                {
                    "detail": response_data.get("returnMessage")
                    or "SchoolPay rejected the payment request."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        payment_reference = response_data.get("paymentReference")
        if not payment_reference:
            return Response(
                {"detail": "SchoolPay did not return a payment reference."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        with transaction.atomic():
            locked = (
                StudentTuitionPayment.objects.select_for_update()
                .filter(pk=charge.pk)
                .first()
            )
            if locked is None:
                return Response(
                    {"detail": "Form fee charge missing."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            locked.payment_method = "mobile_money"
            locked.payment_reference = str(payment_reference)
            locked.transaction_id = ext_ref
            locked.notes = (
                f"{reason}. student={student.student_id or student.reg_no or student.pk} "
                f"phone={phone} externalReference={ext_ref}."
            )
            locked.status = "pending"
            locked.save(
                update_fields=[
                    "payment_method",
                    "payment_reference",
                    "transaction_id",
                    "notes",
                    "status",
                    "updated_at",
                ]
            )
            charge = locked

        return Response(
            {
                "payment_reference": payment_reference,
                "external_reference": ext_ref,
                "status": "PENDING",
                "amount": float(amount),
                "currency": "UGX",
                "form_fee": _form_fee_status_dict(student, charge),
                "detail": "Payment prompt sent. Approve on your phone.",
            },
            status=status.HTTP_201_CREATED,
        )


class ExemptionFormFeePaymentStatusView(APIView):
    """
    GET /api/admissions/change_requests/exemption/form_fee/pay/<payment_ref>
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
            .select_related("fee_head")
            .first()
        )
        if not payment or not is_exemption_form_fee_charge(payment):
            return Response(
                {"detail": "Payment not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if payment.status == "completed":
            sync_exemption_form_fee_paid_at(payment)
            receipt_url = ""
            receipt_no = payment.receipt_number or ""
            if receipt_no.startswith("http"):
                receipt_url = receipt_no
            else:
                try:
                    data = SchoolPayClient().check_status(payment.payment_reference)
                    receipt_url = (data.get("receiptUrl") or data.get("receiptNumber") or "")
                    if isinstance(receipt_url, str) and not receipt_url.startswith("http"):
                        receipt_url = ""
                    if not receipt_no:
                        receipt_no = (data.get("receiptReference") or "") or receipt_no
                except Exception:
                    logger.exception("SchoolPay receipt lookup failed for %s", payment_ref)
            return Response(
                {
                    "status": "PAID",
                    "receipt_number": receipt_no,
                    "receipt_url": receipt_url,
                    "transaction_id": payment.transaction_id or "",
                    "form_fee": ensure_exemption_form_fee_access(
                        student, charged_by=None
                    ),
                }
            )

        try:
            outcome = reconcile_pending_tuition_payment(payment)
        except Exception:
            logger.exception(
                "Exemption form fee status reconcile failed for ref %s", payment_ref
            )
            outcome = "error"

        payment.refresh_from_db()
        if payment.status == "completed" or outcome == "paid":
            sync_exemption_form_fee_paid_at(payment)
        elif outcome == "failed":
            # Keep bill open for retry.
            clear_exemption_form_stk_attempt(payment)
            payment.refresh_from_db()

        return Response(
            {
                "status": _api_status(payment)
                if payment.payment_reference
                else ("FAILED" if outcome == "failed" else _api_status(payment)),
                "receipt_number": payment.receipt_number or "",
                "transaction_id": payment.transaction_id or "",
                "form_fee": _form_fee_status_dict(student, payment),
            }
        )


class CancelExemptionFormFeePaymentView(APIView):
    """
    POST /api/admissions/change_requests/exemption/form_fee/pay/cancel
    Clears a stuck pending MoMo prompt so the student can try again.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        student = get_admitted_student_for_user(request.user)
        if not student:
            return Response(
                {"detail": "Admitted student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        charge = _ensure_form_fee_charge(student, charged_by=None)
        if form_fee_paid_for_charge(student, charge):
            return Response(
                {
                    "detail": "Exemption form fee is already paid.",
                    "status": "PAID",
                    "form_fee": _form_fee_status_dict(student, charge),
                }
            )

        ref = (request.data.get("payment_reference") or "").strip()
        if ref and (charge.payment_reference or "").strip() and ref != (
            charge.payment_reference or ""
        ).strip():
            return Response(
                {"detail": "Payment reference does not match the open form-fee charge."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if charge.status == "completed":
            return Response(
                {
                    "detail": "This charge is already completed.",
                    "form_fee": _form_fee_status_dict(student, charge),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if (charge.payment_reference or "").strip() or charge.payment_method:
            clear_exemption_form_stk_attempt(charge)
            charge.refresh_from_db()

        return Response(
            {
                "detail": "Payment prompt cancelled. You can try again with a mobile money number.",
                "status": "CANCELLED",
                "form_fee": _form_fee_status_dict(student, charge),
            }
        )
