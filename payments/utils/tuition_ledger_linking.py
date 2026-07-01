"""Link SchoolPay tuition ledger rows to admitted students by payment code."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger

ADMISSION_FEE_AMOUNT = Decimal("150000")


def payment_codes_for_student(student: AdmittedStudent) -> set[str]:
    """All identifiers SchoolPay may have used for this student's wallet."""
    codes: set[str] = set()
    for raw in (
        student.student_id,
        student.schoolpay_code,
        student.reg_no,
        getattr(student, "effective_schoolpay_code", None),
    ):
        value = (raw or "").strip()
        if value:
            codes.add(value)
    return codes


def find_admitted_student_by_payment_code(code: str) -> AdmittedStudent | None:
    """Resolve an admitted student from a SchoolPay studentPaymentCode."""
    ident = (code or "").strip()
    if not ident:
        return None
    return (
        AdmittedStudent.objects.filter(
            Q(student_id__iexact=ident)
            | Q(schoolpay_code__iexact=ident)
            | Q(reg_no__iexact=ident)
        )
        .select_related("student_user", "application")
        .order_by("-updated_at")
        .first()
    )


def tuition_ledger_queryset_for_student(student: AdmittedStudent):
    """Ledger rows that belong to this student (linked or by payment code)."""
    codes = payment_codes_for_student(student)
    if not codes:
        return TuitionLedger.objects.filter(student=student)
    return TuitionLedger.objects.filter(
        Q(student=student) | Q(student_payment_code__in=codes)
    )


def relink_tuition_ledgers_for_student(student: AdmittedStudent) -> int:
    """
    Attach orphan SchoolPay ledger rows to the student when payment codes match.

    Returns the number of ledger rows updated.
    """
    codes = payment_codes_for_student(student)
    if not codes:
        return 0

    updated = 0
    qs = TuitionLedger.objects.filter(student_payment_code__in=codes).filter(
        Q(student__isnull=True) | ~Q(student_id=student.pk)
    )
    for ledger in qs.iterator():
        ledger.student = student
        update_fields = ["student"]
        if student.student_user_id and ledger.user_id is None:
            ledger.user = student.student_user
            update_fields.append("user")
        ledger.save(update_fields=update_fields)
        updated += 1

    if updated:
        sync_admission_fee_paid_from_ledger(student)
    return updated


def sync_admission_fee_paid_from_ledger(student: AdmittedStudent) -> bool:
    """Set admission_fee_paid when completed ledger credits meet the commitment threshold."""
    if student.admission_fee_paid:
        return False

    total = Decimal("0")
    for row in tuition_ledger_queryset_for_student(student).filter(
        transaction_completion_status="Completed"
    ):
        total += row.amount or Decimal("0")
        if total >= ADMISSION_FEE_AMOUNT:
            student.admission_fee_paid = True
            student.admission_fee_paid_at = timezone.now()
            student.save(
                update_fields=["admission_fee_paid", "admission_fee_paid_at", "updated_at"]
            )
            return True
    return False
