"""Bulk import legacy fee balances for existing admitted students."""
from __future__ import annotations

import csv
import io
import logging
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from admissions.models import AdmittedStudent
from admissions.student_bulk_import import _parse_upload_file

logger = logging.getLogger(__name__)

FEE_BALANCE_IMPORT_HEADERS = [
    "reg_no",
    "student_id",
    "fees_paid_ugx",
    "fees_paid_reference",
    "fees_outstanding_ugx",
    "admission_fee_paid",
]


def _parse_decimal_amount(raw: str, field_name: str) -> Decimal:
    text = (raw or "").strip().replace(",", "")
    if not text:
        return Decimal("0")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{field_name} must be a number.") from exc
    if amount < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    return amount


def _parse_yes_no(raw: str) -> bool:
    return (raw or "").strip().lower() in ("1", "true", "yes", "y")


def row_has_legacy_fee_data(row: dict) -> bool:
    """True when the row supplies legacy fee balance columns with meaningful values."""
    if _parse_yes_no(row.get("admission_fee_paid", "")):
        return True
    for key in ("fees_paid_ugx", "fees_outstanding_ugx"):
        raw = (row.get(key) or "").strip().replace(",", "")
        if not raw:
            continue
        try:
            if Decimal(raw) > 0:
                return True
        except InvalidOperation:
            return True
    return False


def apply_legacy_fee_balances(
    admitted: AdmittedStudent,
    row: dict,
    *,
    admitted_by,
) -> dict:
    """
    Record legacy tuition paid / outstanding for an existing admitted student.
    """
    from payments.models import StudentTuitionPayment
    from payments.programme_enrollment_activation import (
        activate_programme_enrollment_after_commitment_payment,
    )

    paid_ugx = _parse_decimal_amount(row.get("fees_paid_ugx", ""), "fees_paid_ugx")
    outstanding_ugx = _parse_decimal_amount(
        row.get("fees_outstanding_ugx", ""), "fees_outstanding_ugx"
    )
    mark_admission_paid = _parse_yes_no(row.get("admission_fee_paid", ""))

    if paid_ugx <= 0 and outstanding_ugx <= 0 and not mark_admission_paid:
        raise ValueError(
            "Provide at least one of: fees_paid_ugx, fees_outstanding_ugx, or admission_fee_paid=yes."
        )

    result = {
        "fees_paid_recorded": False,
        "fees_paid_ugx": None,
        "fees_outstanding_recorded": False,
        "fees_outstanding_ugx": None,
        "admission_fee_paid_set": False,
        "enrollment_activated": False,
    }

    if mark_admission_paid and not admitted.admission_fee_paid:
        admitted.admission_fee_paid = True
        admitted.admission_fee_paid_at = timezone.now()
        admitted.save(update_fields=["admission_fee_paid", "admission_fee_paid_at", "updated_at"])
        result["admission_fee_paid_set"] = True

    if paid_ugx > 0:
        ref = (row.get("fees_paid_reference") or "").strip() or f"legacy-fees-{admitted.reg_no}"
        txn_id = f"LEGACY-PAID-{admitted.pk}-{ref}"[:100]
        if StudentTuitionPayment.objects.filter(transaction_id=txn_id).exists():
            raise ValueError(
                f"A legacy payment with reference '{ref}' was already imported for this student."
            )
        StudentTuitionPayment.objects.create(
            student=admitted,
            source="ad_hoc",
            label="Legacy system — tuition paid (import)",
            amount=paid_ugx,
            currency="UGX",
            payment_method="other",
            status="completed",
            transaction_id=txn_id,
            payment_reference=ref[:100],
            receipt_number=ref[:100],
            paid_at=timezone.now(),
            verified_by=admitted_by,
            verified_at=timezone.now(),
            notes="Fee balance import: legacy tuition paid.",
        )
        result["fees_paid_recorded"] = True
        result["fees_paid_ugx"] = float(paid_ugx)

    if outstanding_ugx > 0:
        txn_id = f"LEGACY-DUE-{admitted.pk}"[:100]
        if not StudentTuitionPayment.objects.filter(transaction_id=txn_id).exists():
            StudentTuitionPayment.objects.create(
                student=admitted,
                source="ad_hoc",
                label="Legacy system — outstanding balance (import)",
                amount=outstanding_ugx,
                currency="UGX",
                payment_method="",
                status="pending",
                transaction_id=txn_id,
                payment_reference=f"legacy-due-{admitted.reg_no}"[:100],
                charged_by=admitted_by,
                notes="Fee balance import: legacy outstanding balance.",
            )
        result["fees_outstanding_recorded"] = True
        result["fees_outstanding_ugx"] = float(outstanding_ugx)

    if paid_ugx > 0 or mark_admission_paid or admitted.admission_fee_paid:
        activation = activate_programme_enrollment_after_commitment_payment(
            admitted, activated_by=admitted_by
        )
        result["enrollment_activated"] = bool(activation.get("activated"))

    return result


def _resolve_student(row: dict) -> AdmittedStudent:
    reg_no = row.get("reg_no", "").strip()
    student_id = row.get("student_id", "").strip()
    if not reg_no and not student_id:
        raise ValueError("reg_no or student_id is required to identify the student.")

    qs = AdmittedStudent.objects.filter(is_admitted=True)
    if reg_no and student_id:
        student = qs.filter(reg_no=reg_no, student_id=student_id).first()
        if student is None:
            raise ValueError(
                f"No admitted student with reg_no '{reg_no}' and student_id '{student_id}'."
            )
        return student

    if reg_no:
        student = qs.filter(reg_no=reg_no).first()
        if student is None:
            raise ValueError(f"No admitted student with reg_no '{reg_no}'.")
        return student

    student = qs.filter(student_id=student_id).first()
    if student is None:
        raise ValueError(f"No admitted student with student_id '{student_id}'.")
    return student


def _require_fee_columns(headers: list[str]) -> list[str]:
    missing = []
    if "reg_no" not in headers and "student_id" not in headers:
        missing.append("reg_no or student_id")
    return missing


def process_fee_balance_import(*, uploaded_file, imported_by) -> dict:
    headers, rows = _parse_upload_file(uploaded_file)
    missing = _require_fee_columns(headers)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")
    if not rows:
        raise ValueError("No data rows found in file.")

    updated = 0
    failed = 0
    errors: list[str] = []
    results: list[dict] = []

    for row in rows:
        row_num = row.get("__row__", "?")
        try:
            with transaction.atomic():
                student = _resolve_student(row)
                fee_result = apply_legacy_fee_balances(
                    student, row, admitted_by=imported_by
                )
            updated += 1
            results.append(
                {
                    "id": student.id,
                    "reg_no": student.reg_no,
                    "student_id": student.student_id,
                    "name": student.full_name,
                    **fee_result,
                }
            )
        except ValueError as exc:
            failed += 1
            errors.append(f"Row {row_num}: {exc}")
        except Exception as exc:
            failed += 1
            logger.exception("Fee balance import row %s failed", row_num)
            errors.append(f"Row {row_num}: {exc}")

    enrollment_activated_rows = sum(1 for r in results if r.get("enrollment_activated"))

    return {
        "updated": updated,
        "failed": failed,
        "enrollment_activated_rows": enrollment_activated_rows,
        "errors": errors[:100],
        "students": results[:50],
        "required_columns": FEE_BALANCE_IMPORT_HEADERS,
    }


def build_fee_balance_import_template_csv() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(FEE_BALANCE_IMPORT_HEADERS)
    writer.writerow(
        [
            "26/1/100/D/0001",
            "",
            "150000",
            "LEG-RCPT-001",
            "500000",
            "yes",
        ]
    )
    return buf.getvalue()
