"""Nationality-based amounts/currencies for FeePlanRule rows (semester tuition billing)."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Tuple

from admissions.applicant_category import (
    APPLICANT_CATEGORY_INTERNATIONAL,
    category_from_nationality,
    normalize_applicant_category,
)
from admissions.models import AdmittedStudent


def is_international_student(student: AdmittedStudent) -> bool:
    """True when this student should be billed the international fee column.

    Applicant type International always wins. Otherwise nationality decides
    (Uganda / Kenya / Tanzania = local). Default applicant_category is local,
    so nationality must still be checked or international tuition never applies.
    """
    app = getattr(student, "application", None)
    if not app:
        return False
    if normalize_applicant_category(getattr(app, "applicant_category", None)) == (
        APPLICANT_CATEGORY_INTERNATIONAL
    ):
        return True
    return (
        category_from_nationality(getattr(app, "nationality", None))
        == APPLICANT_CATEGORY_INTERNATIONAL
    )


def effective_amount_currency(rule, international: bool) -> Tuple[Decimal, str]:
    if international and getattr(rule, "amount_international", None) is not None:
        amt = rule.amount_international or Decimal("0")
        cur = (getattr(rule, "currency_international", None) or "").strip()[:3]
        if not cur:
            cur = (getattr(rule, "currency", None) or "UGX").strip()[:3] or "UGX"
        return amt, cur.upper()
    amt = rule.amount or Decimal("0")
    cur = (rule.currency or "UGX").strip()[:3] or "UGX"
    return amt, cur.upper()


def required_by_currency(rules: list, international: bool) -> dict[str, Decimal]:
    out: defaultdict[str, Decimal] = defaultdict(Decimal)
    for r in rules:
        amt, cur = effective_amount_currency(r, international)
        if amt > 0:
            out[cur] += amt
    return dict(out)


def paid_by_currency(student: AdmittedStudent, allowed_rule_ids: set[int] | None = None):
    from .models import StudentTuitionPayment

    if allowed_rule_ids is None:
        from payments.student_payment_allocation import payment_credits_by_currency

        return payment_credits_by_currency(student)

    out: defaultdict[str, Decimal] = defaultdict(Decimal)
    qs = StudentTuitionPayment.objects.filter(student=student, status="completed", is_waived=False)
    if not allowed_rule_ids:
        return {}
    qs = qs.filter(fee_plan_rule_id__in=allowed_rule_ids)
    for p in qs:
        cur = (p.currency or "UGX").strip()[:3] or "UGX"
        out[cur.upper()] += p.amount or Decimal("0")
    return dict(out)
