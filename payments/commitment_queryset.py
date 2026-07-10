"""DB-level commitment fee annotations and filters for admitted students."""
from __future__ import annotations

from decimal import Decimal

from django.db.models import DecimalField, F, IntegerField, OuterRef, Q, Subquery, Sum, Value
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
    """Sum all completed SchoolPay ledger credits matching this student's identifiers."""
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


def filter_by_commitment_met(qs, commitment_met: bool | None):
    """
    Filter admitted students by commitment fee status.

    Met when admission_fee_paid is true or total UGX credits >= threshold.
    """
    if commitment_met is None:
        return qs
    qs = annotate_commitment_ugx_paid(qs)
    met_q = Q(admission_fee_paid=True) | Q(
        commitment_paid_ugx__gte=COMMITMENT_FEE_THRESHOLD
    )
    if commitment_met:
        return qs.filter(met_q)
    return qs.filter(admission_fee_paid=False).filter(
        Q(commitment_paid_ugx__lt=COMMITMENT_FEE_THRESHOLD)
        | Q(commitment_paid_ugx__isnull=True)
    )
