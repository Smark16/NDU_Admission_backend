"""
Pool SchoolPay + portal payments and allocate credit across fee lines (commitment = first UGX slice of tuition).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from admissions.models import AdmittedStudent

from payments.models import FeePlanRule, StudentTuitionPayment, TuitionLedger
from payments.billing_visibility import billing_date_iso, billing_date_reached
from payments.student_fee_pricing import effective_amount_currency, is_international_student
from payments.utils.tuition_ledger_linking import tuition_ledger_queryset_for_student

COMMITMENT_FEE_THRESHOLD = Decimal("150000")


@dataclass
class DemandLine:
    kind: str  # tuition_structure | scheduled_other | ad_hoc
    rule_id: int | None = None
    charge_id: int | None = None
    fee_head: str = ""
    description: str = ""
    amount: Decimal = Decimal("0")
    currency: str = "UGX"
    payable_year: int | None = None
    payable_term: int | None = None
    milestone_reached: bool = True
    billing_reached: bool = True
    paid_amount: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    status: str = "due"  # due | paid | not_due
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinanceAllocation:
    international: bool
    primary_currency: str
    credits_by_currency: dict[str, Decimal]
    commitment_paid_ugx: Decimal
    commitment_met: bool
    commitment_balance: Decimal
    demand_lines: list[DemandLine]
    total_required: Decimal
    total_paid: Decimal
    balance: Decimal
    percentage_paid: float
    tuition_structure_total: Decimal
    scheduled_other_due: Decimal
    ad_hoc_total: Decimal
    required_by_currency: dict[str, Decimal]
    paid_by_currency: dict[str, Decimal]


def _norm_ccy(currency: str | None) -> str:
    return (currency or "UGX").strip()[:3].upper() or "UGX"


def payment_credits_by_currency(student: AdmittedStudent) -> dict[str, Decimal]:
    """Completed portal payments + SchoolPay ledger, deduplicated by receipt/reference."""
    out: defaultdict[str, Decimal] = defaultdict(Decimal)
    seen: set[str] = set()

    for p in StudentTuitionPayment.objects.filter(
        student=student, status="completed", is_waived=False
    ):
        ref = (p.receipt_number or p.payment_reference or p.transaction_id or "").strip()
        key = f"stp:{ref}" if ref else f"stp:id:{p.id}"
        if key in seen:
            continue
        seen.add(key)
        ccy = _norm_ccy(p.currency)
        out[ccy] += p.amount or Decimal("0")

    for row in tuition_ledger_queryset_for_student(student).filter(
        transaction_completion_status="Completed"
    ):
        ref = (row.schoolpay_receipt_number or row.source_channel_transaction_id or "").strip()
        key = f"led:{ref}" if ref else f"led:id:{row.id}"
        if key in seen:
            continue
        seen.add(key)
        out["UGX"] += row.amount or Decimal("0")

    return dict(out)


def _tuition_rule_sort_key(rule: FeePlanRule) -> tuple:
    code = ""
    if rule.fee_head_id:
        code = (rule.fee_head.code or "").upper()
    is_tuition = code == "TUITION_FEE" or (
        rule.fee_head_id and rule.fee_head.category == "tuition"
    )
    return (
        rule.semester_id or 0,
        0 if is_tuition else 1,
        rule.order or 0,
        rule.id,
    )


def _line_is_billable(line: DemandLine) -> bool:
    if not line.billing_reached:
        return False
    if line.kind == "scheduled_other" and not line.milestone_reached:
        return False
    return True


def _build_demand_lines(student: AdmittedStudent, international: bool) -> list[DemandLine]:
    from payments.fee_exemptions import active_fee_exemptions_for_student, is_fee_head_exempted
    from payments.student_portal_finance import (
        _adhoc_charges_for_student,
        _applicable_other_schedule_rules,
        _milestone_reached,
        _rules_for_student,
        _student_curriculum_year_term,
    )

    lines: list[DemandLine] = []
    cy, ct = _student_curriculum_year_term(student)
    exemptions = active_fee_exemptions_for_student(student)

    tuition_rules = sorted(_rules_for_student(student), key=_tuition_rule_sort_key)
    for rule in tuition_rules:
        amt, cur = effective_amount_currency(rule, international)
        if amt <= 0:
            continue
        sem = rule.semester
        billable = billing_date_reached(rule)
        lines.append(
            DemandLine(
                kind="tuition_structure",
                rule_id=rule.id,
                fee_head=rule.fee_head.name if rule.fee_head_id else "Tuition",
                description=sem.name if sem else "Programme tuition",
                amount=amt,
                currency=cur,
                billing_reached=billable,
                extra={
                    "semester_id": rule.semester_id,
                    "semester_name": sem.name if sem else "",
                    "semester_year_of_study": sem.year_of_study if sem else None,
                    "semester_term_number": sem.term_number if sem else None,
                    "semester_order": sem.order if sem else None,
                    "program_batch_id": rule.program_batch_id,
                    "program_batch_name": (
                        rule.program_batch.name if rule.program_batch_id else None
                    ),
                    "installment_number": rule.installment_number,
                    "due_date_days": rule.due_date_days,
                    "billing_date": billing_date_iso(rule),
                    "fee_head_id": rule.fee_head_id,
                },
            )
        )

    for rule in _applicable_other_schedule_rules(student):
        py = int(rule.payable_year_of_study)
        pt = int(rule.payable_term_number)
        if is_fee_head_exempted(
            exemptions,
            rule.fee_head_id,
            payable_year=py,
            payable_term=pt,
        ):
            continue
        reached = _milestone_reached(cy, ct, py, pt)
        billable = billing_date_reached(rule)
        amt, cur = effective_amount_currency(rule, international)
        if amt <= 0:
            continue
        lines.append(
            DemandLine(
                kind="scheduled_other",
                rule_id=rule.id,
                fee_head=rule.fee_head.name if rule.fee_head_id else "",
                description=f"Year {py}, Term {pt}",
                amount=amt,
                currency=cur,
                payable_year=py,
                payable_term=pt,
                milestone_reached=reached,
                billing_reached=billable,
                extra={
                    "program_batch_id": rule.program_batch_id,
                    "program_batch_name": (
                        rule.program_batch.name if rule.program_batch_id else None
                    ),
                    "billing_date": billing_date_iso(rule),
                    "fee_head_id": rule.fee_head_id,
                },
            )
        )

    for charge in _adhoc_charges_for_student(student):
        if charge.is_waived:
            continue
        cur = _norm_ccy(charge.currency)
        amt = charge.amount or Decimal("0")
        if amt <= 0:
            continue
        lines.append(
            DemandLine(
                kind="ad_hoc",
                charge_id=charge.id,
                fee_head=charge.fee_head.name if charge.fee_head_id else "Charge",
                description=charge.label or "Ad-hoc charge",
                amount=amt,
                currency=cur,
                extra={"charge_status": charge.status, "fee_head_id": charge.fee_head_id},
            )
        )

    return lines


def _allocate_pools_to_lines(
    lines: list[DemandLine], credits: dict[str, Decimal]
) -> None:
    pools = {_norm_ccy(k): v for k, v in credits.items()}

    def take_from_pool(ccy: str, amount: Decimal) -> Decimal:
        c = _norm_ccy(ccy)
        available = pools.get(c, Decimal("0"))
        applied = min(available, amount)
        pools[c] = available - applied
        return applied

    for line in lines:
        if not _line_is_billable(line):
            line.paid_amount = Decimal("0")
            line.balance = line.amount
            line.status = "not_due"
            continue

        need = line.amount
        line.paid_amount = take_from_pool(line.currency, need)
        line.balance = max(need - line.paid_amount, Decimal("0"))
        if line.balance <= 0:
            line.status = "paid"
        else:
            line.status = "due"


def build_finance_allocation(student: AdmittedStudent) -> FinanceAllocation:
    international = is_international_student(student)
    credits = payment_credits_by_currency(student)
    lines = _build_demand_lines(student, international)
    _allocate_pools_to_lines(lines, credits)

    required_by: defaultdict[str, Decimal] = defaultdict(Decimal)
    for line in lines:
        if not _line_is_billable(line):
            continue
        if line.kind == "ad_hoc" and line.extra.get("charge_status") not in (
            "pending",
            "completed",
        ):
            continue
        required_by[line.currency] += line.amount

    if required_by:
        primary = max(required_by.keys(), key=lambda k: float(required_by[k]))
    else:
        primary = "USD" if international else "UGX"

    total_required = required_by.get(primary, Decimal("0"))
    total_paid = credits.get(primary, Decimal("0"))
    balance = max(total_required - total_paid, Decimal("0"))
    pct = float((total_paid / total_required * Decimal("100"))) if total_required > 0 else 0.0

    ugx_credit = credits.get("UGX", Decimal("0"))
    commitment_paid = min(ugx_credit, COMMITMENT_FEE_THRESHOLD)
    admission_paid = bool(getattr(student, "admission_fee_paid", False))
    commitment_met = commitment_paid >= COMMITMENT_FEE_THRESHOLD or admission_paid
    commitment_balance = max(COMMITMENT_FEE_THRESHOLD - commitment_paid, Decimal("0"))

    scheduled_due = sum(
        line.balance
        for line in lines
        if line.kind == "scheduled_other"
        and _line_is_billable(line)
        and line.status == "due"
        and line.currency == primary
    )

    adhoc_total = sum(
        line.amount
        for line in lines
        if line.kind == "ad_hoc"
        and line.extra.get("charge_status") in ("pending", "completed")
        and line.currency == primary
    )

    paid_by = {k: float(v) for k, v in credits.items()}

    return FinanceAllocation(
        international=international,
        primary_currency=primary,
        credits_by_currency=credits,
        commitment_paid_ugx=commitment_paid,
        commitment_met=commitment_met,
        commitment_balance=commitment_balance,
        demand_lines=lines,
        total_required=total_required,
        total_paid=total_paid,
        balance=balance,
        percentage_paid=round(pct, 1),
        tuition_structure_total=sum(
            line.amount
            for line in lines
            if line.kind == "tuition_structure"
            and line.billing_reached
            and line.currency == primary
        ),
        scheduled_other_due=scheduled_due,
        ad_hoc_total=adhoc_total,
        required_by_currency=dict(required_by),
        paid_by_currency=paid_by,
    )


def tuition_registration_totals(
    student: AdmittedStudent,
    *,
    current_term_only: bool = True,
) -> dict[str, Any]:
    """
    Tuition amounts for the registration % gate.

    Uses allocated paid_amount on tuition_structure lines (not the raw credit pool),
    optionally scoped to the student's current year/term.
    """
    from payments.student_portal_finance import _student_curriculum_year_term

    alloc = build_finance_allocation(student)
    cy, ct = _student_curriculum_year_term(student)

    lines = [
        ln
        for ln in alloc.demand_lines
        if ln.kind == "tuition_structure" and _line_is_billable(ln)
    ]
    if current_term_only:
        scoped: list[DemandLine] = []
        for ln in lines:
            y = ln.extra.get("semester_year_of_study")
            t = ln.extra.get("semester_term_number")
            if y is None or t is None:
                scoped.append(ln)
            elif int(y) == cy and int(t) == ct:
                scoped.append(ln)
        lines = scoped

    by_currency: dict[str, dict[str, Decimal]] = {}
    for ln in lines:
        ccy = _norm_ccy(ln.currency)
        bucket = by_currency.setdefault(
            ccy, {"required": Decimal("0"), "paid": Decimal("0")}
        )
        bucket["required"] += ln.amount
        bucket["paid"] += ln.paid_amount

    if by_currency:
        primary = max(by_currency.keys(), key=lambda k: float(by_currency[k]["required"]))
    else:
        primary = "USD" if is_international_student(student) else "UGX"

    primary_bucket = by_currency.get(primary, {"required": Decimal("0"), "paid": Decimal("0")})
    req = primary_bucket["required"]
    paid = primary_bucket["paid"]
    pct = float((paid / req * Decimal("100"))) if req > 0 else 0.0

    return {
        "has_tuition_rules": bool(lines),
        "line_count": len(lines),
        "by_currency": by_currency,
        "primary_currency": primary,
        "total_required": req,
        "total_paid_on_tuition": paid,
        "percentage_paid": round(pct, 1),
        "current_year_of_study": cy,
        "current_term_number": ct,
    }


def allocation_rule_paid(allocation: FinanceAllocation, rule_id: int, currency: str) -> Decimal:
    ccy = _norm_ccy(currency)
    for line in allocation.demand_lines:
        if line.rule_id == rule_id and _norm_ccy(line.currency) == ccy:
            return line.paid_amount
    return Decimal("0")
