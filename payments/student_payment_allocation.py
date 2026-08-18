"""
Pool SchoolPay + portal payments and allocate credit across fee lines.

Open demand is scoped to the student's current curriculum year/term so continuing
/ batch-imported students are not charged historical tuition that would absorb
SchoolPay credit before functional and other fees.

When prior terms exist, payments are split by date:
- history (before current-term start) is allocated onto prior-term fee lines
- leftover history credit (overpayment) carries forward into open/current demand
- payments on/after current-term start also clear open (current) demand
- any credit still left after open demand is prepaid toward future terms

Commitment still uses the full UGX credit pool.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from django.utils import timezone

from admissions.models import AdmittedStudent

from payments.models import FeePlanRule, StudentTuitionPayment, TuitionLedger
from payments.billing_visibility import (
    adhoc_charge_billing_date,
    billing_date_iso,
    billing_date_reached,
    fee_head_code,
    is_exemption_adhoc_charge,
    is_exemption_form_fee_charge,
)
from payments.student_fee_pricing import effective_amount_currency, is_international_student
from payments.utils.tuition_ledger_linking import (
    completed_ledger_status_q,
    relink_tuition_ledgers_for_student,
    tuition_ledger_queryset_for_student,
)

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
    status: str = "due"  # due | paid | not_due | settled
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
    ad_hoc_not_yet_due_total: Decimal
    required_by_currency: dict[str, Decimal]
    paid_by_currency: dict[str, Decimal]
    lifetime_paid_by_currency: dict[str, float] = field(default_factory=dict)
    # Unpaid prior-term demand still owed (shown as "balance carried forward").
    balance_carried_forward: Decimal = Decimal("0")
    # Credit left after settling all prior + currently billable lines (next-semester prepaid).
    prepaid_credit_by_currency: dict[str, float] = field(default_factory=dict)
    prepaid_credit: Decimal = Decimal("0")


def _norm_ccy(currency: str | None) -> str:
    return (currency or "UGX").strip()[:3].upper() or "UGX"


def _as_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def payment_credits_by_currency(
    student: AdmittedStudent,
    *,
    on_or_after: date | None = None,
    before: date | None = None,
) -> dict[str, Decimal]:
    """Completed portal payments + SchoolPay ledger, deduplicated by receipt/reference.

    ``on_or_after`` / ``before`` date-scope which payments enter the pool
    (used to split prior-term history from current-term open demand).
    """
    out: defaultdict[str, Decimal] = defaultdict(Decimal)
    seen: set[str] = set()

    def _in_window(paid_d: date | None) -> bool:
        if on_or_after is not None:
            if paid_d is None or paid_d < on_or_after:
                return False
        if before is not None:
            if paid_d is None or paid_d >= before:
                return False
        return True

    for p in StudentTuitionPayment.objects.filter(
        student=student, status="completed", is_waived=False
    ):
        paid_d = _as_date(p.paid_at) or _as_date(p.created_at)
        if not _in_window(paid_d):
            continue
        ref = (p.receipt_number or p.payment_reference or p.transaction_id or "").strip()
        key = f"stp:{ref}" if ref else f"stp:id:{p.id}"
        if key in seen:
            continue
        seen.add(key)
        ccy = _norm_ccy(p.currency)
        amt = p.amount or Decimal("0")
        # Internal reallocation: do not treat as a new receipt; earmark against the pool
        # so tuition coverage drops by this amount and the other charge can be settled.
        from payments.credit_allocation import is_credit_reallocation_payment

        if is_credit_reallocation_payment(p):
            out[ccy] -= amt
            continue
        # Dedicated exemption-form-fee receipts are not tuition credit.
        if is_exemption_form_fee_charge(p):
            continue
        out[ccy] += amt

    for row in tuition_ledger_queryset_for_student(student).filter(
        completed_ledger_status_q()
    ):
        paid_d = _as_date(row.payment_date_time)
        if not _in_window(paid_d):
            continue
        ref = (row.schoolpay_receipt_number or row.source_channel_transaction_id or "").strip()
        key = f"led:{ref}" if ref else f"led:id:{row.id}"
        if key in seen:
            continue
        seen.add(key)
        out["UGX"] += row.amount or Decimal("0")

    return dict(out)


def _open_demand_credit_cutoff(lines: list[DemandLine]) -> date | None:
    """
    If prior curriculum terms were settled outside the portal, only payments from
    the current term window should clear open demand.
    """
    if not any(ln.extra.get("prior_period_settled") for ln in lines):
        return None
    cutoffs: list[date] = []
    for ln in lines:
        if not _line_is_billable(ln):
            continue
        for key in ("semester_start_date", "billing_date"):
            d = _as_date(ln.extra.get(key))
            if d is not None:
                cutoffs.append(d)
    return min(cutoffs) if cutoffs else None


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


def _curriculum_pair(year, term) -> tuple[int, int] | None:
    try:
        if year is None or term is None:
            return None
        y, t = int(year), int(term)
    except (TypeError, ValueError):
        return None
    if y < 1 or t < 1:
        return None
    return y, t


def _line_is_prior_curriculum_term(line: DemandLine, cy: int, ct: int) -> bool:
    """True when the fee line belongs to a year/term before the student's current position."""
    if line.kind == "tuition_structure":
        pair = _curriculum_pair(
            line.extra.get("semester_year_of_study"),
            line.extra.get("semester_term_number"),
        )
    elif line.kind == "scheduled_other":
        pair = _curriculum_pair(line.payable_year, line.payable_term)
    else:
        return False
    if pair is None:
        return False
    return pair < (cy, ct)


def _line_is_future_curriculum_term(line: DemandLine, cy: int, ct: int) -> bool:
    if line.kind == "tuition_structure":
        pair = _curriculum_pair(
            line.extra.get("semester_year_of_study"),
            line.extra.get("semester_term_number"),
        )
    elif line.kind == "scheduled_other":
        pair = _curriculum_pair(line.payable_year, line.payable_term)
    else:
        return False
    if pair is None:
        return False
    return pair > (cy, ct)


def _line_is_billable(line: DemandLine) -> bool:
    if line.extra.get("prior_period_settled"):
        return False
    if not line.billing_reached:
        return False
    if line.kind == "scheduled_other" and not line.milestone_reached:
        return False
    return True


def _build_demand_lines(student: AdmittedStudent, international: bool) -> list[DemandLine]:
    from payments.billing_visibility import (
        curriculum_period_label,
        resolve_semester_for_year_term,
    )
    from payments.fee_exemptions import active_fee_exemptions_for_student, is_fee_head_exempted
    from payments.student_portal_finance import (
        _adhoc_charges_for_student,
        _applicable_other_schedule_rules,
        _milestone_reached,
        _rules_for_student,
        _student_curriculum_year_term,
        _student_program_batch_id,
    )

    lines: list[DemandLine] = []
    cy, ct = _student_curriculum_year_term(student)
    exemptions = active_fee_exemptions_for_student(student)
    program = getattr(student, "admitted_program", None)
    student_pb_id = _student_program_batch_id(student)

    from admissions.exemption_services import (
        prorate_tuition_for_course_exemptions,
        semester_paper_counts_for_exemptions,
        year_fully_course_exempted,
    )

    # Cache full-year / full-term exemption checks (tuition + functional waived).
    year_fully_exempt_cache: dict[int, bool] = {}
    term_fully_exempt_cache: dict[tuple[int, int], bool] = {}

    def _year_fully_exempt(year: int) -> bool:
        if year not in year_fully_exempt_cache:
            year_fully_exempt_cache[year] = year_fully_course_exempted(
                student, year_of_study=year
            )
        return year_fully_exempt_cache[year]

    def _term_fully_exempt(year: int, term: int) -> bool:
        key = (year, term)
        if key not in term_fully_exempt_cache:
            counts = semester_paper_counts_for_exemptions(
                student, year_of_study=year, term_number=term
            )
            term_fully_exempt_cache[key] = bool(
                counts and counts["total_papers"] > 0 and counts["non_exempted_papers"] <= 0
            )
        return term_fully_exempt_cache[key]

    # Advanced entry (e.g. HOD promote after exemptions): no tuition/functional
    # for terms before the student's entry year/term — covered by per-paper fees.
    entry_pair: tuple[int, int] | None = None
    has_course_exemptions = False
    try:
        enr = student.programme_enrollment
        if enr is not None:
            ey = int(enr.entry_year_of_study or 0)
            et = int(enr.entry_term_number or 0)
            if ey >= 1 and et >= 1 and (ey, et) > (1, 1):
                entry_pair = (ey, et)
            from Programs.models import StudentCurriculumOverride

            has_course_exemptions = StudentCurriculumOverride.objects.filter(
                enrollment=enr,
                override_type="exempted",
            ).exists()
    except Exception:
        entry_pair = None
        has_course_exemptions = False

    # Exemptions / promotion: apply the cohort tuition structure immediately
    # (amounts, waivers, proration) even when the semester billing date has not
    # arrived yet. Curriculum position still gates future terms below.
    pick_structure_despite_billing_date = bool(entry_pair or has_course_exemptions)

    tuition_rules = sorted(_rules_for_student(student), key=_tuition_rule_sort_key)
    for rule in tuition_rules:
        amt, cur = effective_amount_currency(rule, international)
        if amt <= 0:
            continue
        sem = rule.semester
        # Partial exemptions: prorate TUITION only.
        # Full term / full year / pre-entry terms: omit TUITION + FUNCTIONAL —
        # student pays only per-paper EXEMPTION_COURSE charges for those papers.
        fee_code = (rule.fee_head.code or "").upper() if rule.fee_head_id else ""
        is_tuition_head = fee_code == "TUITION_FEE"
        is_functional_head = fee_code == "FUNCTIONAL_FEE" or "FUNCTIONAL" in fee_code
        proration_meta: dict[str, Any] | None = None

        sem_year = int(sem.year_of_study) if sem is not None and sem.year_of_study else None
        sem_term = int(sem.term_number) if sem is not None and sem.term_number else None

        if pick_structure_despite_billing_date and (is_tuition_head or is_functional_head):
            billable = True
        elif (
            (is_tuition_head or is_functional_head)
            and sem_year is not None
            and sem_term is not None
            and sem_year == cy
            and sem_term == ct
        ):
            # Enrolled current term: apply SchoolPay already received even if the
            # scheduled billing date is still in the future.
            billable = True
        else:
            billable = billing_date_reached(rule)

        if (
            (is_tuition_head or is_functional_head)
            and sem_year is not None
            and sem_term is not None
        ):
            if entry_pair is not None and (sem_year, sem_term) < entry_pair:
                continue
            if _year_fully_exempt(sem_year):
                continue
            if _term_fully_exempt(sem_year, sem_term):
                continue

        if (
            is_tuition_head
            and sem_year is not None
            and sem_term is not None
        ):
            amt, proration_meta = prorate_tuition_for_course_exemptions(
                student,
                amt,
                year_of_study=sem_year,
                term_number=sem_term,
            )
            if amt <= 0:
                continue
        line = DemandLine(
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
                "semester_start_date": (
                    sem.start_date.isoformat() if sem and sem.start_date else None
                ),
                "semester_end_date": (
                    sem.end_date.isoformat() if sem and sem.end_date else None
                ),
                "program_batch_id": rule.program_batch_id,
                "program_batch_name": (
                    rule.program_batch.name if rule.program_batch_id else None
                ),
                "installment_number": rule.installment_number,
                "due_date_days": rule.due_date_days,
                "billing_date": billing_date_iso(rule),
                "fee_head_id": rule.fee_head_id,
                "calendar_type": (
                    getattr(program, "calendar_type", None) or "semester"
                ),
                **(
                    {
                        "tuition_prorated_for_exemptions": True,
                        "exemption_total_papers": proration_meta["total_papers"],
                        "exemption_exempted_papers": proration_meta["exempted_papers"],
                        "exemption_non_exempted_papers": proration_meta[
                            "non_exempted_papers"
                        ],
                    }
                    if proration_meta and proration_meta.get("exempted_papers", 0) > 0
                    else {}
                ),
            },
        )
        # Continuing / batch-imported cohorts: only current curriculum term is open.
        # Past terms are outside open demand; credits for open demand are date-scoped
        # separately so historical SchoolPay does not clear the current term.
        if _line_is_prior_curriculum_term(line, cy, ct):
            line.extra["prior_period_settled"] = True
        elif _line_is_future_curriculum_term(line, cy, ct):
            line.billing_reached = False
        lines.append(line)

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
        pb_id = rule.program_batch_id or student_pb_id
        sem = resolve_semester_for_year_term(
            program_batch_id=pb_id,
            year_of_study=py,
            term_number=pt,
        )
        period_label = curriculum_period_label(
            py,
            pt,
            program=program,
            semester_name=sem.name if sem else None,
        )
        line = DemandLine(
            kind="scheduled_other",
            rule_id=rule.id,
            fee_head=rule.fee_head.name if rule.fee_head_id else "",
            description=period_label,
            amount=amt,
            currency=cur,
            payable_year=py,
            payable_term=pt,
            milestone_reached=reached,
            billing_reached=billable,
            extra={
                "program_batch_id": pb_id,
                "program_batch_name": (
                    rule.program_batch.name
                    if rule.program_batch_id
                    else None
                ),
                "billing_date": billing_date_iso(rule),
                "fee_head_id": rule.fee_head_id,
                # Align with tuition_structure so Room & Board groups under the same semester.
                "semester_id": sem.id if sem else None,
                "semester_name": (sem.name if sem else "") or period_label,
                "semester_year_of_study": (
                    sem.year_of_study if sem else py
                ),
                "semester_term_number": sem.term_number if sem else pt,
                "semester_order": sem.order if sem else None,
                "semester_start_date": (
                    sem.start_date.isoformat() if sem and sem.start_date else None
                ),
                "semester_end_date": (
                    sem.end_date.isoformat() if sem and sem.end_date else None
                ),
                "calendar_type": (
                    getattr(program, "calendar_type", None) or "semester"
                ),
            },
        )
        if _line_is_prior_curriculum_term(line, cy, ct):
            line.extra["prior_period_settled"] = True
        lines.append(line)

    for charge in _adhoc_charges_for_student(student):
        if charge.is_waived:
            continue
        # Only open (pending) charges are demand. Completed ad-hoc rows are already paid
        # (and completed amounts are already in the credit pool).
        if getattr(charge, "status", None) != "pending":
            continue
        cur = _norm_ccy(charge.currency)
        amt = charge.amount or Decimal("0")
        if amt <= 0:
            continue
        # When staff split a manual charge across chosen semesters, each part is tagged
        # with a Semester for ledger placement. Ordinary ad-hoc waits until that term
        # starts; exemption form/course fees stay immediately due so they appear on
        # student list balances as soon as Accounts posts them.
        sem = charge.semester
        billable = True
        payable_year = payable_term = None
        extra: dict[str, Any] = {
            "charge_status": charge.status,
            "fee_head_id": charge.fee_head_id,
            "fee_head_code": fee_head_code(charge),
        }
        if is_exemption_form_fee_charge(charge):
            extra["exclude_from_tuition"] = True
        if sem is not None:
            payable_year, payable_term = sem.year_of_study, sem.term_number
            eff_date = adhoc_charge_billing_date(charge)
            extra.update(
                {
                    "semester_id": sem.id,
                    "semester_name": sem.name,
                    "semester_year_of_study": sem.year_of_study,
                    "semester_term_number": sem.term_number,
                    "semester_start_date": sem.start_date.isoformat() if sem.start_date else None,
                    "billing_date": eff_date.isoformat() if eff_date else None,
                }
            )
            if is_exemption_adhoc_charge(charge):
                billable = True
                extra["exemption_immediate"] = True
            elif eff_date is not None:
                billable = timezone.localdate() >= eff_date
        lines.append(
            DemandLine(
                kind="ad_hoc",
                charge_id=charge.id,
                fee_head=charge.fee_head.name if charge.fee_head_id else "Charge",
                description=charge.label or "Ad-hoc charge",
                amount=amt,
                currency=cur,
                payable_year=payable_year,
                payable_term=payable_term,
                billing_reached=billable,
                extra=extra,
            )
        )

    return lines


def _billing_line_sort_key(line: DemandLine) -> tuple:
    """Oldest semester first; tuition → other programme fees → scheduled (e.g. room) → ad-hoc."""
    y = line.extra.get("semester_year_of_study") or line.payable_year or 0
    t = line.extra.get("semester_term_number") or line.payable_term or 0
    try:
        yi, ti = int(y), int(t)
    except (TypeError, ValueError):
        yi, ti = 0, 0
    start = _as_date(line.extra.get("semester_start_date")) or date.min
    head = (line.fee_head or "").lower()
    if line.kind == "tuition_structure":
        rank = 0 if "tuition" in head else 1
    elif line.kind == "scheduled_other":
        rank = 2
    else:
        rank = 3
    return (yi, ti, start, rank, line.rule_id or 0, line.charge_id or 0)


def _prior_line_sort_key(line: DemandLine) -> tuple:
    return _billing_line_sort_key(line)


def _allocate_pools_to_lines(
    lines: list[DemandLine],
    credits: dict[str, Decimal],
    *,
    target: Literal["prior", "open", "all"] = "all",
) -> dict[str, Decimal]:
    """Apply credit pools to matching demand lines. Returns leftover credit by currency."""
    pools = {_norm_ccy(k): Decimal(str(v)) for k, v in credits.items() if v}

    def take_from_pool(ccy: str, amount: Decimal) -> Decimal:
        c = _norm_ccy(ccy)
        available = pools.get(c, Decimal("0"))
        applied = min(available, amount)
        pools[c] = available - applied
        return applied

    if target in ("open", "all"):
        for line in lines:
            if line.extra.get("prior_period_settled"):
                continue
            if not _line_is_billable(line):
                line.paid_amount = Decimal("0")
                line.balance = line.amount
                line.status = "not_due"

    if target == "prior":
        ordered = sorted(
            (ln for ln in lines if ln.extra.get("prior_period_settled")),
            key=_prior_line_sort_key,
        )
    elif target == "open":
        ordered = sorted(
            (
                ln
                for ln in lines
                if not ln.extra.get("prior_period_settled") and _line_is_billable(ln)
            ),
            key=_billing_line_sort_key,
        )
    else:
        ordered = [
            ln
            for ln in lines
            if ln.extra.get("prior_period_settled") or _line_is_billable(ln)
        ]
        ordered = sorted(
            (ln for ln in ordered if ln.extra.get("prior_period_settled")),
            key=_prior_line_sort_key,
        ) + [
            ln
            for ln in lines
            if not ln.extra.get("prior_period_settled") and _line_is_billable(ln)
        ]

    # Exemption form fee is MoMo-prompt only. Do not spend SchoolPay / tuition credit on it.
    for line in ordered:
        if line.extra.get("exclude_from_tuition"):
            line.paid_amount = Decimal("0")
            line.balance = line.amount
            line.status = "due"
            continue
        need = line.amount
        # When open allocation runs after prior, keep any amount already applied.
        already = line.paid_amount if target == "open" else Decimal("0")
        still_need = max(need - already, Decimal("0"))
        applied = take_from_pool(line.currency, still_need)
        line.paid_amount = already + applied
        line.balance = max(need - line.paid_amount, Decimal("0"))
        if line.extra.get("prior_period_settled"):
            # Outside open demand; Paid/Balance still reflect history allocation.
            line.status = "settled" if line.balance <= 0 else "prior"
        elif line.balance <= 0:
            line.status = "paid"
        else:
            line.status = "due"

    return {k: v for k, v in pools.items() if v > 0}


def _persist_settled_exemption_form_charges(lines: list[DemandLine]) -> None:
    """No-op: form fee is completed only by the exemption MoMo prompt / webhook."""
    return


def build_finance_allocation(student: AdmittedStudent) -> FinanceAllocation:
    # Relink existing ledger rows only. Never pull SchoolPay ranges here —
    # a 90-day school-wide ingest blocked gunicorn and made Admit hang.
    try:
        relink_tuition_ledgers_for_student(student)
    except Exception:
        pass
    international = is_international_student(student)
    credits_all = payment_credits_by_currency(student)
    lines = _build_demand_lines(student, international)
    cutoff = _open_demand_credit_cutoff(lines)

    if cutoff is not None:
        credits_history = payment_credits_by_currency(student, before=cutoff)
        credits_open = payment_credits_by_currency(student, on_or_after=cutoff)
        # Historical SchoolPay/portal payments → prior semester fee lines (oldest first).
        leftover_history = _allocate_pools_to_lines(lines, credits_history, target="prior")
        # Overpayment from earlier terms + current-term payments → open billable demand.
        merged_open: dict[str, Decimal] = defaultdict(Decimal)
        for ccy, amt in leftover_history.items():
            merged_open[_norm_ccy(ccy)] += Decimal(str(amt))
        for ccy, amt in credits_open.items():
            merged_open[_norm_ccy(ccy)] += Decimal(str(amt))
        leftover_open = _allocate_pools_to_lines(lines, dict(merged_open), target="open")
        # Open-window credits for reporting: current-term receipts + surplus from prior terms.
        credits_open = dict(merged_open)
    else:
        credits_open = credits_all
        leftover_open = _allocate_pools_to_lines(lines, credits_all, target="all")

    _persist_settled_exemption_form_charges(lines)

    # Required/paid/balance carry forward: include prior-term lines (unpaid history)
    # alongside current billable demand, matching the same predicate already used by
    # student_billing_lines() / full_outstanding_balance_status() (exam card gate), so
    # a shortfall from an earlier term doesn't silently vanish once the student moves
    # on to the next term.
    required_by: defaultdict[str, Decimal] = defaultdict(Decimal)
    paid_by_all: defaultdict[str, Decimal] = defaultdict(Decimal)
    for line in lines:
        is_prior = bool(line.extra.get("prior_period_settled"))
        if line.extra.get("exclude_from_tuition"):
            continue
        if not is_prior and not _line_is_billable(line):
            continue
        if line.kind == "ad_hoc" and line.extra.get("charge_status") not in (
            "pending",
            "completed",
        ):
            continue
        required_by[line.currency] += line.amount
        paid_by_all[line.currency] += line.paid_amount

    if required_by:
        primary = max(required_by.keys(), key=lambda k: float(required_by[k]))
    else:
        primary = "USD" if international else "UGX"

    total_required = required_by.get(primary, Decimal("0"))
    # Paid toward all included (prior + current) demand lines — ties out exactly
    # against total_required since each line's paid_amount + balance == amount.
    total_paid = paid_by_all.get(primary, Decimal("0"))
    balance = max(total_required - total_paid, Decimal("0"))
    pct = float((total_paid / total_required * Decimal("100"))) if total_required > 0 else 0.0

    ugx_credit = credits_all.get("UGX", Decimal("0"))
    commitment_paid = min(ugx_credit, COMMITMENT_FEE_THRESHOLD)
    admission_paid = bool(getattr(student, "admission_fee_paid", False))
    commitment_met = commitment_paid >= COMMITMENT_FEE_THRESHOLD or admission_paid
    commitment_balance = max(COMMITMENT_FEE_THRESHOLD - commitment_paid, Decimal("0"))

    scheduled_due = sum(
        line.balance
        for line in lines
        if line.kind == "scheduled_other"
        and (line.extra.get("prior_period_settled") or _line_is_billable(line))
        and line.status in ("due", "prior")
        and line.currency == primary
    )

    # "Due now" — same billable gate used for total_required/balance, so this figure
    # never contradicts what the student is actually asked to pay.
    adhoc_total = sum(
        line.amount
        for line in lines
        if line.kind == "ad_hoc"
        and line.extra.get("charge_status") in ("pending", "completed")
        and line.currency == primary
        and (line.extra.get("prior_period_settled") or _line_is_billable(line))
    )
    # Scheduled but not yet due (e.g. a charge split onto a future semester) — surfaced
    # separately so it doesn't silently vanish from view, it just isn't billed yet.
    adhoc_not_yet_due = sum(
        line.amount
        for line in lines
        if line.kind == "ad_hoc"
        and line.extra.get("charge_status") == "pending"
        and line.currency == primary
        and not line.extra.get("prior_period_settled")
        and not _line_is_billable(line)
    )

    paid_by = {k: float(v) for k, v in credits_open.items()}
    lifetime_by = {k: float(v) for k, v in credits_all.items()}
    prepaid_by = {k: float(v) for k, v in leftover_open.items()}
    prepaid_primary = Decimal(str(leftover_open.get(primary, 0) or 0))
    # Outstanding from earlier terms — what the UI labels "Balance carried forward".
    carried_forward = sum(
        (
            line.balance
            for line in lines
            if line.extra.get("prior_period_settled")
            and line.currency == primary
            and line.balance > 0
        ),
        Decimal("0"),
    )

    return FinanceAllocation(
        international=international,
        primary_currency=primary,
        credits_by_currency=credits_open,
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
            and _line_is_billable(line)
            and line.currency == primary
        ),
        scheduled_other_due=scheduled_due,
        ad_hoc_total=adhoc_total,
        ad_hoc_not_yet_due_total=adhoc_not_yet_due,
        required_by_currency=dict(required_by),
        paid_by_currency=paid_by,
        lifetime_paid_by_currency=lifetime_by,
        balance_carried_forward=carried_forward,
        prepaid_credit_by_currency=prepaid_by,
        prepaid_credit=prepaid_primary,
    )


def tuition_registration_totals(
    student: AdmittedStudent,
    *,
    current_term_only: bool = True,
    alloc: FinanceAllocation | None = None,
) -> dict[str, Any]:
    """
    Fee amounts for the registration % gate / displayed tuition %.

    Uses allocated paid_amount on all billable current-term fee lines
    (tuition + functional / practical / room & board / other scheduled fees,
    and billable ad-hoc charges) — not tuition-only, and not prior-term carry.
    """
    from payments.student_portal_finance import _student_curriculum_year_term

    if alloc is None:
        alloc = build_finance_allocation(student)
    cy, ct = _student_curriculum_year_term(student)

    def _line_year_term(ln: DemandLine) -> tuple[int | None, int | None]:
        y = ln.extra.get("semester_year_of_study")
        t = ln.extra.get("semester_term_number")
        if y is None or t is None:
            y = ln.payable_year
            t = ln.payable_term
        try:
            yi = int(y) if y is not None else None
            ti = int(t) if t is not None else None
        except (TypeError, ValueError):
            return None, None
        return yi, ti

    lines: list[DemandLine] = []
    for ln in alloc.demand_lines:
        if ln.extra.get("exclude_from_tuition"):
            continue
        if not _line_is_billable(ln):
            continue
        if ln.kind == "ad_hoc" and ln.extra.get("charge_status") not in (
            "pending",
            "completed",
        ):
            continue
        if ln.kind not in ("tuition_structure", "scheduled_other", "ad_hoc"):
            continue
        if current_term_only:
            y, t = _line_year_term(ln)
            # Ad-hoc / unscoped lines count toward the open (current) semester total.
            if y is not None and t is not None and (int(y) != cy or int(t) != ct):
                continue
        lines.append(ln)

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
