"""Detect and remove fee-balance import rows (legacy paid credits + outstanding charges).

These are synthetic StudentTuitionPayment rows created by
``admissions.student_fee_balance_import`` — not SchoolPay ledger or real scholarships.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q, QuerySet

from admissions.models import AdmittedStudent
from payments.models import StudentTuitionPayment

LEGACY_PAID_PREFIX = "LEGACY-PAID-"
LEGACY_DUE_PREFIX = "LEGACY-DUE-"
LEGACY_PAID_LABEL = "Legacy system — fees paid (import credit)"
LEGACY_DUE_LABEL = "Legacy system — outstanding balance (import)"


def legacy_fee_import_queryset(student: AdmittedStudent) -> QuerySet[StudentTuitionPayment]:
    """Rows created by fee-balance import for this student only."""
    return StudentTuitionPayment.objects.filter(student=student).filter(
        Q(transaction_id__startswith=LEGACY_PAID_PREFIX)
        | Q(transaction_id__startswith=LEGACY_DUE_PREFIX)
        | Q(label=LEGACY_PAID_LABEL)
        | Q(label=LEGACY_DUE_LABEL)
    )


def is_legacy_fee_import_row(payment: StudentTuitionPayment) -> bool:
    tid = (payment.transaction_id or "").strip()
    if tid.startswith(LEGACY_PAID_PREFIX) or tid.startswith(LEGACY_DUE_PREFIX):
        return True
    label = (payment.label or "").strip()
    return label in (LEGACY_PAID_LABEL, LEGACY_DUE_LABEL)


def _row_kind(payment: StudentTuitionPayment) -> str:
    tid = (payment.transaction_id or "").strip()
    label = (payment.label or "").strip()
    if tid.startswith(LEGACY_DUE_PREFIX) or label == LEGACY_DUE_LABEL:
        return "outstanding"
    return "paid_credit"


def legacy_fee_row_to_dict(payment: StudentTuitionPayment) -> dict:
    return {
        "id": payment.id,
        "kind": _row_kind(payment),
        "kind_label": (
            "Legacy outstanding (import)"
            if _row_kind(payment) == "outstanding"
            else "Legacy fees paid (import credit)"
        ),
        "source": payment.source,
        "label": payment.label or "",
        "amount": float(payment.amount or 0),
        "currency": (payment.currency or "UGX").strip() or "UGX",
        "status": payment.status,
        "transaction_id": payment.transaction_id or "",
        "payment_reference": payment.payment_reference or "",
        "receipt_number": payment.receipt_number or "",
        "paid_at": payment.paid_at.isoformat() if payment.paid_at else None,
        "created_at": payment.created_at.isoformat() if payment.created_at else None,
        "notes": (payment.notes or "")[:500],
    }


def list_legacy_fee_rows(student: AdmittedStudent) -> list[dict]:
    rows = legacy_fee_import_queryset(student).order_by("-created_at", "-id")
    return [legacy_fee_row_to_dict(p) for p in rows]


def delete_legacy_fee_rows(
    student: AdmittedStudent,
    *,
    payment_ids: list[int] | None = None,
    deleted_by=None,
    request=None,
) -> dict:
    """
    Hard-delete matching legacy import rows.

    If ``payment_ids`` is None or empty, delete all legacy import rows for the student.
    Only LEGACY-PAID / LEGACY-DUE (or matching legacy labels) are removable.
    """
    from audit.utils import log_audit_event

    qs = legacy_fee_import_queryset(student)
    if payment_ids:
        qs = qs.filter(id__in=[int(i) for i in payment_ids])

    targets = list(qs)
    if payment_ids:
        found_ids = {p.id for p in targets}
        missing = [i for i in payment_ids if int(i) not in found_ids]
        if missing:
            raise ValueError(
                "Some ids are not legacy fee-import rows for this student "
                f"(or do not exist): {missing}."
            )

    deleted: list[dict] = []
    with transaction.atomic():
        for payment in targets:
            if not is_legacy_fee_import_row(payment):
                continue
            snapshot = legacy_fee_row_to_dict(payment)
            deleted.append(snapshot)
            payment.delete()

    if deleted and deleted_by is not None:
        summary = "; ".join(
            f"{r['kind']} {r['currency']} {r['amount']:,.0f} (id={r['id']})"
            for r in deleted[:20]
        )
        if len(deleted) > 20:
            summary += f"; …and {len(deleted) - 20} more"
        log_audit_event(
            deleted_by,
            "legacy_fee_delete",
            student,
            (
                f"Deleted {len(deleted)} legacy fee-import row(s) for "
                f"student id={student.pk} reg_no={student.reg_no}: {summary}"
            ),
            request,
        )

    return {
        "deleted_count": len(deleted),
        "deleted": deleted,
    }


def list_students_with_legacy_fee_imports(*, limit: int = 100) -> list[dict]:
    """Students that still have at least one LEGACY-PAID / LEGACY-DUE row."""
    qs = (
        StudentTuitionPayment.objects.filter(
            Q(transaction_id__startswith=LEGACY_PAID_PREFIX)
            | Q(transaction_id__startswith=LEGACY_DUE_PREFIX)
            | Q(label=LEGACY_PAID_LABEL)
            | Q(label=LEGACY_DUE_LABEL)
        )
        .select_related("student", "student__application")
        .order_by("-created_at")
    )
    by_student: dict[int, dict] = {}
    for payment in qs.iterator(chunk_size=200):
        sid = int(payment.student_id)
        if sid not in by_student:
            if len(by_student) >= limit:
                continue
            student = payment.student
            name = getattr(student, "full_name", None) or student.reg_no
            by_student[sid] = {
                "student_pk": sid,
                "student_id": student.student_id,
                "reg_no": student.reg_no,
                "student_name": name,
                "rows": [],
                "row_count": 0,
                "total_amount_ugx": 0.0,
            }
        entry = by_student.get(sid)
        if entry is None:
            continue
        row = legacy_fee_row_to_dict(payment)
        entry["rows"].append(row)
        entry["row_count"] += 1
        if (row.get("currency") or "UGX").upper() == "UGX":
            entry["total_amount_ugx"] += float(row.get("amount") or 0)

    return list(by_student.values())
