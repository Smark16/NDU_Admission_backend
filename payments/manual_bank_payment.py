"""Post a single bank / reconciliation payment onto a student's tuition ledger."""
from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger


def is_manual_bank_ledger(ledger: TuitionLedger) -> bool:
    receipt = (ledger.schoolpay_receipt_number or "").strip()
    raw = ledger.raw_response if isinstance(ledger.raw_response, dict) else {}
    return receipt.startswith("BANK-") or raw.get("source") == "manual_bank_reconciliation"


def get_manual_bank_ledger(ledger_id: int) -> TuitionLedger:
    ledger = TuitionLedger.objects.select_related("student", "student__application", "user").get(
        pk=ledger_id
    )
    if not is_manual_bank_ledger(ledger):
        raise ValueError("This ledger entry is not a manual bank payment.")
    return ledger


def _student_display_name(student: AdmittedStudent) -> str:
    app = getattr(student, "application", None)
    if app is None:
        return (student.reg_no or student.student_id or f"Student {student.pk}").strip()
    parts = [
        getattr(app, "first_name", "") or "",
        getattr(app, "middle_name", "") or "",
        getattr(app, "last_name", "") or "",
    ]
    name = " ".join(p for p in parts if p).strip()
    return name or (student.reg_no or student.student_id or f"Student {student.pk}")


def _payment_code(student: AdmittedStudent) -> str:
    return (
        (getattr(student, "student_id", None) or "").strip()
        or (getattr(student, "schoolpay_code", None) or "").strip()
        or (getattr(student, "reg_no", None) or "").strip()
        or f"STU-{student.pk}"
    )


def _normalize_bank_ref(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (raw or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned[:80] if cleaned else ""


def _parse_amount(raw: Any) -> Decimal:
    try:
        amount = Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, AttributeError, TypeError) as exc:
        raise ValueError("Amount must be a valid number.") from exc
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    if amount > Decimal("999999999.99"):
        raise ValueError("Amount is too large.")
    return amount.quantize(Decimal("0.01"))


def _parse_payment_when(raw: Any):
    if raw in (None, ""):
        return timezone.now()
    if isinstance(raw, datetime):
        dt = raw
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt
    if isinstance(raw, date):
        dt = datetime.combine(raw, time.min)
        return timezone.make_aware(dt, timezone.get_current_timezone())

    text = str(raw).strip()
    dt = parse_datetime(text)
    if dt is None:
        d = parse_date(text)
        if d is not None:
            dt = datetime.combine(d, time.min)
    if dt is None:
        raise ValueError("payment_date must be a valid date or datetime (YYYY-MM-DD).")
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _user_label(user) -> str:
    if user is None:
        return ""
    return (
        getattr(user, "get_full_name", lambda: "")()
        or getattr(user, "email", "")
        or str(getattr(user, "pk", "") or "")
    )


def _build_detail(*, notes: str, action_note: str) -> str:
    detail_parts = [p for p in [(notes or "").strip(), action_note] if p]
    return " | ".join(detail_parts)[:2000]


def _receipt_for_student(student_pk: int, ref: str) -> str:
    receipt = f"BANK-{student_pk}-{ref}"
    return receipt[:100]


@transaction.atomic
def post_manual_bank_payment(
    *,
    student: AdmittedStudent,
    amount,
    bank_reference: str,
    payment_date=None,
    notes: str = "",
    bank_name: str = "",
    posted_by=None,
) -> TuitionLedger:
    """
    Credit one Completed TuitionLedger row from a bank reconciliation line.

    Receipt id is unique: BANK-{student_id}-{normalized_ref}
    """
    amt = _parse_amount(amount)
    ref = _normalize_bank_ref(bank_reference)
    if not ref:
        raise ValueError("Bank reference / slip number is required.")

    receipt = _receipt_for_student(student.pk, ref)

    if TuitionLedger.objects.filter(schoolpay_receipt_number=receipt).exists():
        raise ValueError(
            f"A payment with bank reference “{bank_reference}” is already posted "
            f"for this student (receipt {receipt})."
        )

    when = _parse_payment_when(payment_date)
    code = _payment_code(student)
    name = _student_display_name(student)
    channel = (bank_name or "").strip() or "Bank (manual)"
    poster_label = _user_label(posted_by)
    clearance_note = (
        f"Posted by {poster_label} from bank reconciliation"
        if poster_label
        else "Posted by staff from bank reconciliation"
    )
    detail = _build_detail(notes=notes, action_note=clearance_note)

    ledger = TuitionLedger.objects.create(
        user=posted_by if getattr(posted_by, "pk", None) else None,
        student=student,
        amount=amt,
        payment_date_time=when,
        schoolpay_receipt_number=receipt,
        settlement_bank_code=(bank_name or "").strip()[:50] or None,
        source_channel_trans_detail=detail,
        source_channel_transaction_id=ref[:100],
        source_payment_channel=channel[:100],
        student_name=name[:255],
        student_payment_code=code[:100],
        student_registration_number=(student.reg_no or "")[:100],
        transaction_completion_status="Completed",
        raw_response={
            "source": "manual_bank_reconciliation",
            "bank_reference": bank_reference.strip(),
            "bank_name": (bank_name or "").strip(),
            "notes": (notes or "").strip(),
            "posted_by_id": getattr(posted_by, "pk", None),
            "posted_at": timezone.now().isoformat(),
        },
        reconciled=True,
    )
    return ledger


@transaction.atomic
def update_manual_bank_payment(
    *,
    ledger: TuitionLedger,
    amount=None,
    bank_reference=None,
    payment_date=None,
    notes=None,
    bank_name=None,
    edited_by=None,
) -> TuitionLedger:
    if not is_manual_bank_ledger(ledger):
        raise ValueError("This ledger entry is not a manual bank payment.")

    student = ledger.student
    if student is None:
        raise ValueError("This bank payment is not linked to a student.")

    raw = dict(ledger.raw_response) if isinstance(ledger.raw_response, dict) else {}
    current_notes = raw.get("notes") if notes is None else notes

    if amount is not None:
        ledger.amount = _parse_amount(amount)

    if bank_reference is not None:
        ref = _normalize_bank_ref(bank_reference)
        if not ref:
            raise ValueError("Bank reference / slip number is required.")
        receipt = _receipt_for_student(student.pk, ref)
        clash = (
            TuitionLedger.objects.filter(schoolpay_receipt_number=receipt)
            .exclude(pk=ledger.pk)
            .exists()
        )
        if clash:
            raise ValueError(
                f"A payment with bank reference “{bank_reference}” is already posted "
                f"for this student (receipt {receipt})."
            )
        ledger.schoolpay_receipt_number = receipt
        ledger.source_channel_transaction_id = ref[:100]
        raw["bank_reference"] = bank_reference.strip()

    if payment_date is not None and payment_date != "":
        ledger.payment_date_time = _parse_payment_when(payment_date)

    if bank_name is not None:
        channel = (bank_name or "").strip() or "Bank (manual)"
        ledger.settlement_bank_code = (bank_name or "").strip()[:50] or None
        ledger.source_payment_channel = channel[:100]
        raw["bank_name"] = (bank_name or "").strip()

    if notes is not None:
        raw["notes"] = (notes or "").strip()

    editor_label = _user_label(edited_by)
    action_note = (
        f"Updated by {editor_label} from bank reconciliation"
        if editor_label
        else "Updated by staff from bank reconciliation"
    )
    ledger.source_channel_trans_detail = _build_detail(
        notes=str(current_notes or ""),
        action_note=action_note,
    )
    raw["source"] = "manual_bank_reconciliation"
    raw["last_edited_by_id"] = getattr(edited_by, "pk", None)
    raw["last_edited_at"] = timezone.now().isoformat()
    ledger.raw_response = raw
    ledger.reconciled = True
    ledger.transaction_completion_status = "Completed"
    ledger.save()
    return ledger


@transaction.atomic
def delete_manual_bank_payment(*, ledger: TuitionLedger) -> dict[str, Any]:
    if not is_manual_bank_ledger(ledger):
        raise ValueError("This ledger entry is not a manual bank payment.")
    snapshot = {
        "id": ledger.id,
        "student_id": ledger.student_id,
        "amount": str(ledger.amount),
        "receipt": ledger.schoolpay_receipt_number,
        "bank_reference": ledger.source_channel_transaction_id,
        "student_name": ledger.student_name,
    }
    ledger.delete()
    return snapshot


def manual_bank_ledger_queryset():
    return TuitionLedger.objects.filter(
        Q(schoolpay_receipt_number__startswith="BANK-")
        | Q(raw_response__source="manual_bank_reconciliation")
    )
