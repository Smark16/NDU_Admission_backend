"""Link SchoolPay tuition ledger rows to admitted students by payment code."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger

ADMISSION_FEE_AMOUNT = Decimal("150000")


def completed_ledger_status_q() -> Q:
    return Q(transaction_completion_status__iexact="completed")


def wallet_payment_codes_for_student(student: AdmittedStudent) -> set[str]:
    """SchoolPay wallet identifiers only (reg. no. may change)."""
    codes: set[str] = set()
    for raw in (student.student_id, student.schoolpay_code):
        value = (raw or "").strip()
        if value:
            codes.add(value)
    return codes


def completed_ledger_total_ugx(codes: set[str]) -> Decimal:
    if not codes:
        return Decimal("0")
    total = Decimal("0")
    q = Q()
    for code in codes:
        q |= Q(student_payment_code__iexact=code)
    for row in TuitionLedger.objects.filter(q).filter(completed_ledger_status_q()).only("amount"):
        total += row.amount or Decimal("0")
    return total


def student_payment_code_locked(student: AdmittedStudent) -> bool:
    """True when completed SchoolPay ledger credits exist on the wallet code."""
    return completed_ledger_total_ugx(wallet_payment_codes_for_student(student)) > 0


def schoolpay_wallet_api_fields(student: AdmittedStudent) -> dict:
    locked = student_payment_code_locked(student)
    wallet_codes = wallet_payment_codes_for_student(student)
    total = completed_ledger_total_ugx(wallet_codes)
    code = (student.student_id or student.schoolpay_code or "").strip()
    warning = ""
    if locked and code:
        warning = (
            f"SchoolPay code {code} has recorded payments (UGX {total:,.0f}). "
            "Do not change the payment code. You may still update programme and reg. number."
        )
    return {
        "schoolpay_payment_code_locked": locked,
        "schoolpay_ledger_total_ugx": float(total),
        "schoolpay_payment_warning": warning,
    }


def should_register_student_with_schoolpay(student: AdmittedStudent) -> bool:
    """Skip new SchoolPay wallet creation when a paid wallet code already exists."""
    if student.is_registered_with_schoolpay:
        return False
    if student_payment_code_locked(student):
        return False
    if (student.student_id or "").strip():
        return False
    return True


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
            compact = value.replace(" ", "").replace("/", "")
            if compact and compact != value:
                codes.add(compact)
    return codes


def tuition_ledger_queryset_for_student(student: AdmittedStudent):
    """Ledger rows that belong to this student (linked or by payment code)."""
    codes = payment_codes_for_student(student)
    q = Q(student=student)
    for code in codes:
        q |= Q(student_payment_code__iexact=code)
    reg = (student.reg_no or "").strip()
    if reg:
        q |= Q(student_registration_number__iexact=reg)
    if getattr(student, "student_user_id", None):
        q |= Q(user_id=student.student_user_id)
    return TuitionLedger.objects.filter(q)


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


def attach_extra_payment_codes_to_student(
    student: AdmittedStudent,
    extra_codes: list[str] | set[str],
) -> int:
    """
    After a programme change SchoolPay may issue a new wallet code while older
    payments remain on the previous code. Attach those ledger rows to the
    current student and keep the old code on ``schoolpay_code`` when the
    locked ``student_id`` is already the new wallet.
    """
    codes = {(c or "").strip() for c in extra_codes if (c or "").strip()}
    if not codes:
        return 0

    qs = TuitionLedger.objects.filter(student_payment_code__in=codes).filter(
        Q(student__isnull=True) | ~Q(student_id=student.pk)
    )
    ledgers = list(qs.only("id", "user_id", "student_id", "student_payment_code"))
    for ledger in ledgers:
        ledger.student_id = student.pk
        if student.student_user_id and ledger.user_id is None:
            ledger.user_id = student.student_user_id
    if ledgers:
        TuitionLedger.objects.bulk_update(ledgers, ["student", "user"])

    current_id = (student.student_id or "").strip()
    current_sp = (student.schoolpay_code or "").strip()
    update_fields: list[str] = []
    # Prefer keeping the locked/new wallet on student_id; park prior code on schoolpay_code.
    prior = sorted(codes, key=lambda c: (not c.isdigit(), len(c), c))[0]
    if current_id and prior != current_id and (not current_sp or current_sp == current_id):
        student.schoolpay_code = prior
        update_fields.append("schoolpay_code")
    elif not current_id:
        student.student_id = prior
        update_fields.append("student_id")
        if not current_sp:
            student.schoolpay_code = prior
            update_fields.append("schoolpay_code")
    if update_fields:
        update_fields.append("updated_at")
        student.save(update_fields=list(dict.fromkeys(update_fields)))

    sync_admission_fee_paid_from_ledger(student)
    return len(ledgers)


def relink_tuition_ledgers_for_student(student: AdmittedStudent) -> int:
    """
    Attach orphan SchoolPay ledger rows to the student when payment codes or
    SchoolPay registration number match this admitted student.

    Returns the number of ledger rows updated.
    """
    codes = payment_codes_for_student(student)
    reg = (student.reg_no or "").strip()
    match = Q()
    for code in codes:
        match |= Q(student_payment_code__iexact=code)
    if reg:
        # Orphan rows often keep the reg no even when student_id/code never matched.
        match |= Q(student_registration_number__iexact=reg)
    if not match:
        return 0

    qs = TuitionLedger.objects.filter(match).filter(
        Q(student__isnull=True) | ~Q(student_id=student.pk)
    )
    ledgers = list(qs.only("id", "user_id", "student_id", "student_payment_code"))
    if not ledgers:
        return 0

    for ledger in ledgers:
        ledger.student_id = student.pk
        if student.student_user_id and ledger.user_id is None:
            ledger.user_id = student.student_user_id

    TuitionLedger.objects.bulk_update(ledgers, ["student", "user"])

    # Backfill wallet code when ERP never stored the SchoolPay studentPaymentCode.
    pay_codes = {
        (row.student_payment_code or "").strip()
        for row in ledgers
        if (row.student_payment_code or "").strip()
    }
    update_fields: list[str] = []
    if pay_codes and not (student.student_id or "").strip():
        # Prefer a numeric SchoolPay-style code when present.
        chosen = sorted(pay_codes, key=lambda c: (not c.isdigit(), len(c), c))[0]
        student.student_id = chosen
        update_fields.append("student_id")
    if pay_codes and not (student.schoolpay_code or "").strip():
        chosen = sorted(pay_codes, key=lambda c: (not c.isdigit(), len(c), c))[0]
        student.schoolpay_code = chosen
        update_fields.append("schoolpay_code")
    if update_fields:
        update_fields.append("updated_at")
        student.save(update_fields=update_fields)

    sync_admission_fee_paid_from_ledger(student)
    return len(ledgers)


def sync_admission_fee_paid_from_ledger(student: AdmittedStudent) -> bool:
    """Set admission_fee_paid when completed ledger credits meet the commitment threshold."""
    if student.admission_fee_paid:
        return False

    total = Decimal("0")
    for row in tuition_ledger_queryset_for_student(student).filter(completed_ledger_status_q()):
        total += row.amount or Decimal("0")
        if total >= ADMISSION_FEE_AMOUNT:
            student.admission_fee_paid = True
            student.admission_fee_paid_at = timezone.now()
            student.save(
                update_fields=["admission_fee_paid", "admission_fee_paid_at", "updated_at"]
            )
            return True
    return False
