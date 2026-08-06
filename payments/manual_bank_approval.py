"""Dual-control workflow for manual bank payment post / edit / delete."""
from __future__ import annotations

from django.utils import timezone

from accounts.super_admin import user_is_super_admin
from payments.manual_bank_payment import (
    delete_manual_bank_payment,
    post_manual_bank_payment,
    update_manual_bank_payment,
)
from payments.models import ManualBankPaymentChangeRequest


FINANCE_MANAGER_GROUP = "Finance Manager"
BURSAR_GROUP = "Bursar"
BANK_APPROVER_GROUPS = frozenset({FINANCE_MANAGER_GROUP, BURSAR_GROUP})


def user_is_finance_manager(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        return user.groups.filter(name__iexact=FINANCE_MANAGER_GROUP).exists()
    except Exception:
        return False


def user_is_bursar(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        return user.groups.filter(name__iexact=BURSAR_GROUP).exists()
    except Exception:
        return False


def user_can_approve_manual_bank(user) -> bool:
    if user_is_super_admin(user):
        return True
    if not user or not getattr(user, "is_authenticated", False):
        return False
    try:
        return user.groups.filter(name__in=BANK_APPROVER_GROUPS).exists()
    except Exception:
        return False


def can_approve_change_request(user, change_request: ManualBankPaymentChangeRequest) -> bool:
    if not user_can_approve_manual_bank(user):
        return False
    if change_request.requested_by_id and change_request.requested_by_id == getattr(user, "pk", None):
        # Break-glass: only Super Admin may approve their own request.
        return user_is_super_admin(user)
    return True


def _require_reason(request_type: str, reason: str) -> str:
    text = (reason or "").strip()
    if request_type in (
        ManualBankPaymentChangeRequest.RequestType.UPDATE,
        ManualBankPaymentChangeRequest.RequestType.DELETE,
    ) and not text:
        raise ValueError("A reason is required for edit and delete requests.")
    return text


def create_change_request(
    *,
    request_type: str,
    student,
    requested_by,
    ledger=None,
    payload: dict | None = None,
    reason: str = "",
) -> ManualBankPaymentChangeRequest:
    reason_clean = _require_reason(request_type, reason)
    payload = dict(payload or {})

    if request_type == ManualBankPaymentChangeRequest.RequestType.POST:
        if not student:
            raise ValueError("Student is required.")
        amount = payload.get("amount")
        bank_reference = payload.get("bank_reference") or ""
        if amount in (None, ""):
            raise ValueError("Amount is required.")
        if not str(bank_reference).strip():
            raise ValueError("Bank reference is required.")
    elif request_type in (
        ManualBankPaymentChangeRequest.RequestType.UPDATE,
        ManualBankPaymentChangeRequest.RequestType.DELETE,
    ):
        if ledger is None:
            raise ValueError("Ledger payment is required.")
        if getattr(ledger, "student_id", None) and student and ledger.student_id != student.pk:
            raise ValueError("Ledger does not belong to this student.")
        if student is None:
            student = ledger.student
        if student is None:
            raise ValueError("Bank payment is not linked to a student.")

    if request_type == ManualBankPaymentChangeRequest.RequestType.POST:
        ref = str(payload.get("bank_reference") or "").strip().lower()
        pending_qs = ManualBankPaymentChangeRequest.objects.filter(
            status=ManualBankPaymentChangeRequest.Status.PENDING,
            request_type=request_type,
            student=student,
        )
        for row in pending_qs:
            existing_ref = str((row.payload or {}).get("bank_reference") or "").strip().lower()
            if existing_ref and existing_ref == ref:
                raise ValueError(
                    "A pending post request already exists for this bank reference."
                )
    else:
        pending_exists = ManualBankPaymentChangeRequest.objects.filter(
            status=ManualBankPaymentChangeRequest.Status.PENDING,
            request_type=request_type,
            student=student,
            ledger=ledger,
        ).exists()
        if pending_exists:
            raise ValueError("A pending request already exists for this payment action.")

    return ManualBankPaymentChangeRequest.objects.create(
        request_type=request_type,
        student=student,
        ledger=ledger,
        payload=payload,
        reason=reason_clean,
        requested_by=requested_by,
        status=ManualBankPaymentChangeRequest.Status.PENDING,
    )


def apply_change_request(
    change_request: ManualBankPaymentChangeRequest,
    *,
    reviewed_by,
    review_notes: str = "",
) -> tuple[ManualBankPaymentChangeRequest, object | None]:
    if change_request.status != ManualBankPaymentChangeRequest.Status.PENDING:
        raise ValueError("Only pending requests can be approved.")
    if not can_approve_change_request(reviewed_by, change_request):
        raise PermissionError("You cannot approve this request.")

    payload = change_request.payload or {}
    result = None

    if change_request.request_type == ManualBankPaymentChangeRequest.RequestType.POST:
        result = post_manual_bank_payment(
            student=change_request.student,
            amount=payload.get("amount"),
            bank_reference=payload.get("bank_reference") or "",
            payment_date=payload.get("payment_date"),
            notes=payload.get("notes") or "",
            bank_name=payload.get("bank_name") or "",
            posted_by=change_request.requested_by or reviewed_by,
        )
        change_request.ledger = result
    elif change_request.request_type == ManualBankPaymentChangeRequest.RequestType.UPDATE:
        ledger = change_request.ledger
        if ledger is None:
            raise ValueError("Original payment no longer exists.")
        result = update_manual_bank_payment(
            ledger=ledger,
            amount=payload.get("amount") if "amount" in payload else None,
            bank_reference=payload.get("bank_reference") if "bank_reference" in payload else None,
            payment_date=payload.get("payment_date") if "payment_date" in payload else None,
            notes=payload.get("notes") if "notes" in payload else None,
            bank_name=payload.get("bank_name") if "bank_name" in payload else None,
            edited_by=change_request.requested_by or reviewed_by,
        )
        raw = dict(result.raw_response) if isinstance(result.raw_response, dict) else {}
        raw["approval_reason"] = change_request.reason
        raw["approved_by_id"] = getattr(reviewed_by, "pk", None)
        result.raw_response = raw
        result.save(update_fields=["raw_response"])
    elif change_request.request_type == ManualBankPaymentChangeRequest.RequestType.DELETE:
        ledger = change_request.ledger
        if ledger is None:
            raise ValueError("Original payment no longer exists.")
        result = delete_manual_bank_payment(ledger=ledger)
        change_request.ledger = None
    else:
        raise ValueError("Unknown request type.")

    change_request.status = ManualBankPaymentChangeRequest.Status.APPROVED
    change_request.reviewed_by = reviewed_by
    change_request.reviewed_at = timezone.now()
    change_request.review_notes = (review_notes or "").strip()
    change_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "ledger",
        ]
    )
    return change_request, result


def reject_change_request(
    change_request: ManualBankPaymentChangeRequest,
    *,
    reviewed_by,
    review_notes: str = "",
) -> ManualBankPaymentChangeRequest:
    if change_request.status != ManualBankPaymentChangeRequest.Status.PENDING:
        raise ValueError("Only pending requests can be rejected.")
    if not can_approve_change_request(reviewed_by, change_request):
        raise PermissionError("You cannot reject this request.")
    notes = (review_notes or "").strip()
    if not notes:
        raise ValueError("A rejection note is required.")
    change_request.status = ManualBankPaymentChangeRequest.Status.REJECTED
    change_request.reviewed_by = reviewed_by
    change_request.reviewed_at = timezone.now()
    change_request.review_notes = notes
    change_request.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "review_notes"]
    )
    return change_request


def serialize_change_request(req: ManualBankPaymentChangeRequest) -> dict:
    requester = req.requested_by
    reviewer = req.reviewed_by
    student = req.student
    app = getattr(student, "application", None) if student else None
    student_name = ""
    if app:
        student_name = f"{app.first_name or ''} {app.last_name or ''}".strip()
    if not student_name and student:
        student_name = student.reg_no or student.student_id or f"Student {student.pk}"

    return {
        "id": req.id,
        "request_type": req.request_type,
        "request_type_label": req.get_request_type_display(),
        "status": req.status,
        "student_pk": req.student_id,
        "student_name": student_name,
        "student_id": (student.student_id if student else "") or "",
        "reg_no": (student.reg_no if student else "") or "",
        "ledger_id": req.ledger_id,
        "payload": req.payload or {},
        "reason": req.reason or "",
        "requested_by": (
            (requester.get_full_name() or requester.email or str(requester.pk))
            if requester
            else ""
        ),
        "requested_by_id": req.requested_by_id,
        "requested_at": req.requested_at.isoformat() if req.requested_at else None,
        "reviewed_by": (
            (reviewer.get_full_name() or reviewer.email or str(reviewer.pk))
            if reviewer
            else ""
        ),
        "reviewed_by_id": req.reviewed_by_id,
        "reviewed_at": req.reviewed_at.isoformat() if req.reviewed_at else None,
        "review_notes": req.review_notes or "",
        "can_self_approve_as_super_admin": bool(
            requester and user_is_super_admin(requester)
        ),
    }
