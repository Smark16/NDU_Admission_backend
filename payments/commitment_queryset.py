"""DB-level commitment fee annotations and filters for admitted students."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import (
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from payments.models import StudentTuitionPayment, TuitionLedger
from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

_DECIMAL = DecimalField(max_digits=14, decimal_places=2)


def _zero_decimal():
    return Value(Decimal("0"), output_field=_DECIMAL)


def _portal_ugx_subquery():
    return Subquery(
        StudentTuitionPayment.objects.filter(
            student_id=OuterRef("pk"),
            status="completed",
            is_waived=False,
            currency="UGX",
        )
        .order_by()
        .values("student_id")
        .annotate(total=Sum("amount"))
        .values("total")[:1],
        output_field=_DECIMAL,
    )


def _ledger_ugx_subquery():
    """Sum completed SchoolPay ledger credits matching this student's identifiers."""
    return Subquery(
        TuitionLedger.objects.filter(
            transaction_completion_status="Completed",
        )
        .filter(
            Q(student_id=OuterRef("pk"))
            | Q(student_payment_code=OuterRef("student_id"))
            | Q(student_payment_code=OuterRef("schoolpay_code"))
            | Q(student_payment_code=OuterRef("reg_no"))
        )
        .order_by()
        .annotate(grp=Value(1, output_field=IntegerField()))
        .values("grp")
        .annotate(total=Sum("amount"))
        .values("total")[:1],
        output_field=_DECIMAL,
    )


def annotate_commitment_ugx_paid(qs):
    """Sum completed portal UGX payments + SchoolPay ledger credits per student."""
    if "commitment_paid_ugx" in qs.query.annotations:
        return qs
    return qs.annotate(
        _portal_ugx_paid=Coalesce(_portal_ugx_subquery(), _zero_decimal()),
        _ledger_ugx_paid=Coalesce(_ledger_ugx_subquery(), _zero_decimal()),
    ).annotate(commitment_paid_ugx=F("_portal_ugx_paid") + F("_ledger_ugx_paid"))


def _portal_enough_exists():
    """Portal UGX credits >= commitment threshold (indexed on student_id)."""
    return Exists(
        StudentTuitionPayment.objects.filter(
            student_id=OuterRef("pk"),
            status="completed",
            is_waived=False,
            currency="UGX",
        )
        .values("student_id")
        .annotate(total=Sum("amount"))
        .filter(total__gte=COMMITMENT_FEE_THRESHOLD)
    )


def _ledger_fk_enough_exists():
    """Ledger credits linked by student FK >= threshold (fast path)."""
    return Exists(
        TuitionLedger.objects.filter(
            student_id=OuterRef("pk"),
            transaction_completion_status="Completed",
        )
        .values("student_id")
        .annotate(total=Sum("amount"))
        .filter(total__gte=COMMITMENT_FEE_THRESHOLD)
    )


def _ledger_code_enough_exists():
    """Ledger credits matched by payment code (student_id / schoolpay / reg_no)."""
    return Exists(
        TuitionLedger.objects.filter(
            transaction_completion_status="Completed",
        )
        .filter(
            Q(student_payment_code=OuterRef("student_id"))
            | Q(student_payment_code=OuterRef("schoolpay_code"))
            | Q(student_payment_code=OuterRef("reg_no"))
        )
        .annotate(grp=Value(1, output_field=IntegerField()))
        .values("grp")
        .annotate(total=Sum("amount"))
        .filter(total__gte=COMMITMENT_FEE_THRESHOLD)
    )


def commitment_met_q() -> Q:
    """Full payment-math commitment check (slow on large ledgers — avoid on list pages)."""
    return (
        Q(admission_fee_paid=True)
        | _portal_enough_exists()
        | _ledger_fk_enough_exists()
        | _ledger_code_enough_exists()
    )


def filter_by_commitment_met(
    qs,
    commitment_met: bool | None,
    *,
    strict: bool = False,
):
    """
    Filter admitted students by commitment fee status.

    Fast path (default, ``strict=False``): indexed ``admission_fee_paid`` only.
    Use this for bonafide / directory lists and headcount KPIs.

    Strict path (``strict=True``): also sums portal + SchoolPay ledger credits.
    Keep for finance tooling / reminder jobs — not list COUNT queries.
    """
    if commitment_met is None:
        return qs
    if not strict:
        return qs.filter(admission_fee_paid=bool(commitment_met))
    met = commitment_met_q()
    if commitment_met:
        return qs.filter(met)
    return qs.filter(~met)


def sync_admission_fee_paid_flags(*, batch_size: int = 500, max_students: int | None = None) -> dict:
    """
    Backfill ``admission_fee_paid`` for admitted students who already met commitment
    via portal/ledger but still have the flag false.

    Run once on production after deploy so the fast list filter matches reality::

        python manage.py sync_commitment_flags
    """
    from admissions.models import AdmittedStudent

    unpaid = (
        AdmittedStudent.objects.filter(is_admitted=True, admission_fee_paid=False)
        .order_by("id")
        .values_list("id", flat=True)
    )
    ids = list(unpaid[:max_students] if max_students else unpaid)
    updated = 0
    for i in range(0, len(ids), batch_size):
        chunk = ids[i : i + batch_size]
        chunk_qs = AdmittedStudent.objects.filter(id__in=chunk)
        to_mark = list(
            filter_by_commitment_met(chunk_qs, True, strict=True).values_list("id", flat=True)
        )
        if to_mark:
            updated += AdmittedStudent.objects.filter(id__in=to_mark).update(
                admission_fee_paid=True,
                admission_fee_paid_at=timezone.now(),
            )
    return {"candidates": len(ids), "updated": updated}

