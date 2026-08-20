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


def _text_marks_international(value: str | None) -> bool:
    t = (value or "").upper()
    return "INTL" in t or "INTERNATIONAL" in t


def is_international_student(student: AdmittedStudent) -> bool:
    """True when this student should be billed the international fee column.

    International campus / programme / INTL intake always uses that column.
    Applicant type International also wins. Otherwise nationality decides
    (Uganda / Kenya / Tanzania = local).
    """
    if _text_marks_international(getattr(getattr(student, "admitted_program", None), "name", None)):
        return True
    if _text_marks_international(getattr(getattr(student, "admitted_campus", None), "name", None)):
        return True
    if _text_marks_international(getattr(getattr(student, "admitted_batch", None), "name", None)):
        return True
    intended = getattr(student, "intended_program_batch", None)
    if _text_marks_international(getattr(intended, "name", None)):
        return True
    try:
        enr = student.programme_enrollment
        pb = getattr(enr, "program_batch", None) if enr is not None else None
        if _text_marks_international(getattr(pb, "name", None)):
            return True
    except Exception:
        pass

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
    intl_amt = getattr(rule, "amount_international", None)
    local_amt = rule.amount or Decimal("0")
    if international:
        has_intl = intl_amt is not None and Decimal(str(intl_amt)) > 0
        if has_intl:
            cur = (getattr(rule, "currency_international", None) or "").strip()[:3]
            if not cur:
                cur = (getattr(rule, "currency", None) or "UGX").strip()[:3] or "UGX"
            return Decimal(str(intl_amt)), cur.upper()
    amt = local_amt
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
