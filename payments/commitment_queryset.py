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
    """
    Ledger credits matched by payment code (student_id / schoolpay / reg_no).

    Kept separate from the FK path so Postgres can use student_payment_code indexes
    without forcing a full OR scan for every admitted row during list filters.
    """
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
    """
    Commitment met without annotating every row.

    Prefer admission_fee_paid (denormalized when payments land), then Exists checks.
    Avoids the old annotate+filter pattern that made bonafide list COUNT/ORDER crawl.
    """
    return (
        Q(admission_fee_paid=True)
        | _portal_enough_exists()
        | _ledger_fk_enough_exists()
        | _ledger_code_enough_exists()
    )


def filter_by_commitment_met(qs, commitment_met: bool | None):
    """
    Filter admitted students by commitment fee status.

    Met when admission_fee_paid is true or total UGX credits >= threshold.
    """
    if commitment_met is None:
        return qs
    met = commitment_met_q()
    if commitment_met:
        return qs.filter(met)
    return qs.filter(~met)
