"""Student portal: tuition lines (FeePlanRule) and payment totals for semester billing."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from django.db.models import Q
from admissions.models import AdmittedStudent

from payments.batch_semester_fee_helpers import get_or_create_tuition_fee_plan
from payments.models import FeePlanRule, StudentTuitionPayment, TuitionLedger
from payments.other_fee_schedule_views import get_or_create_other_schedule_fee_plan
from payments.student_payment_allocation import (
    COMMITMENT_FEE_THRESHOLD,
    _line_is_billable,
    build_finance_allocation,
)
from payments.utils.tuition_ledger_linking import tuition_ledger_queryset_for_student


def get_admitted_student_for_user(user):
    if not user or not user.is_authenticated:
        return None
    return (
        AdmittedStudent.objects.select_related(
            "admitted_program",
            "admitted_campus",
            "admitted_batch",
            "application",
            "admitted_by",
            "student_user",
            "intended_program_batch",
            "programme_enrollment",
            "programme_enrollment__program_batch",
        )
        .filter(
            Q(application__applicant=user)
            | Q(student_user=user)
            | Q(reg_no=user.username),
            is_admitted=True,
        )
        .first()
    )


def _student_program_batch_id(student: AdmittedStudent) -> int | None:
    try:
        enr = student.programme_enrollment
        if enr is not None and enr.program_batch_id:
            return int(enr.program_batch_id)
    except Exception:
        pass
    if student.intended_program_batch_id:
        return int(student.intended_program_batch_id)

    program = student.admitted_program
    if not program:
        return None

    from Programs.program_batch_resolution import resolve_default_program_batch_for_program

    default_pb = resolve_default_program_batch_for_program(
        program, admission_batch=student.admitted_batch
    )
    if default_pb is not None:
        return int(default_pb.id)

    fee_plan = get_or_create_tuition_fee_plan(program)
    batch_ids = list(
        FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            program_batch_id__isnull=False,
            program_batch__program_id=program.id,
            semester_id__isnull=False,
        )
        .values_list("program_batch_id", flat=True)
        .distinct()
    )
    if len(batch_ids) == 1:
        return int(batch_ids[0])
    return None

def _rules_for_student(student: AdmittedStudent):
    from .feeplanrule_table import ensure_feeplanrule_table

    ensure_feeplanrule_table()
    program = student.admitted_program
    if program is None:
        return []
    fee_plan = get_or_create_tuition_fee_plan(program)
    qs = FeePlanRule.objects.filter(
        fee_plan=fee_plan,
        program_batch__program_id=program.id,
    )
    pb_id = _student_program_batch_id(student)
    if pb_id:
        qs = qs.filter(program_batch_id=pb_id)
    return list(
        qs.select_related("fee_head", "program_batch", "semester").order_by(
            "program_batch_id", "semester_id", "order"
        )
    )


def _student_curriculum_year_term(student: AdmittedStudent) -> tuple[int, int]:
    """Current programme position for milestone fees (defaults to Year 1 Term 1)."""
    try:
        enr = student.programme_enrollment
        if enr is not None:
            y = int(enr.current_year_of_study or 1)
            t = int(enr.current_term_number or 1)
            if y >= 1 and t >= 1:
                return y, t
    except Exception:
        pass
    return 1, 1


def _applicable_other_schedule_rules(student: AdmittedStudent) -> list[FeePlanRule]:
    """Active other-fee rules for this student's programme (and cohort when enrolled)."""
    if not student.admitted_program_id:
        return []
    program = student.admitted_program
    fee_plan = get_or_create_other_schedule_fee_plan(program)
    pb_id = _student_program_batch_id(student)
    qs = (
        FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            is_active=True,
            payable_year_of_study__isnull=False,
            payable_term_number__isnull=False,
        )
        .filter(
            Q(program_id=program.id)
            | Q(program__isnull=True, fee_plan__program_id=program.id)
        )
        .select_related("fee_head", "program_batch")
        .order_by("payable_year_of_study", "payable_term_number", "fee_head__name", "id")
    )
    if pb_id:
        qs = qs.filter(Q(program_batch_id=pb_id) | Q(program_batch__isnull=True))
    else:
        qs = qs.filter(program_batch__isnull=True)
    return list(qs)


def _milestone_reached(current_y: int, current_t: int, pay_y: int, pay_t: int) -> bool:
    if current_y > pay_y:
        return True
    if current_y < pay_y:
        return False
    return current_t >= pay_t


def completed_commitment_paid_ugx(student: AdmittedStudent) -> Decimal:
    """UGX credited toward commitment (capped at threshold; part of tuition pool)."""
    return build_finance_allocation(student).commitment_paid_ugx


def commitment_payment_summary(student: AdmittedStudent) -> dict[str, float | bool]:
    alloc = build_finance_allocation(student)
    return {
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "commitment_paid_ugx": float(alloc.commitment_paid_ugx),
        "commitment_met": alloc.commitment_met,
        "commitment_balance": float(alloc.commitment_balance),
    }


def offer_letter_pdf_url(student: AdmittedStudent, request=None) -> str | None:
    try:
        app = student.application
        if not app or not app.admission_letter_pdf or not app.admission_letter_pdf.name:
            return None
        url = app.admission_letter_pdf.url
        if request is not None:
            return request.build_absolute_uri(url)
        return url
    except Exception:
        return None

def offer_letter_portal_fields(student: AdmittedStudent, request=None) -> dict[str, Any]:
    summary = commitment_payment_summary(student)
    commitment_met = bool(summary["commitment_met"])
    admission_paid = bool(getattr(student, "admission_fee_paid", False))
    eligible = commitment_met or admission_paid
    app = getattr(student, "application", None)
    has_pdf = bool(
        app
        and getattr(app, "admission_letter_pdf", None)
        and getattr(app.admission_letter_pdf, "name", None)
    )
    # pdf_url = offer_letter_pdf_url(student, request) if eligible and has_pdf else None
    pdf_url = offer_letter_pdf_url(student, request) if has_pdf else None
    return {
        **summary,
        "offer_letter_eligible": eligible,
        "offer_letter_pdf_url": pdf_url,
        # "offer_letter_can_download": bool(eligible and has_pdf),
        "offer_letter_can_download": bool(has_pdf),
    }

def other_schedule_rows_and_due_by_currency(
    student: AdmittedStudent, intl: bool | None = None
) -> tuple[list[dict[str, Any]], dict[str, Decimal]]:
    alloc = build_finance_allocation(student)
    rows: list[dict[str, Any]] = []
    due_by_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for line in alloc.demand_lines:
        if line.kind != "scheduled_other":
            continue
        if not line.billing_reached:
            continue
        if line.milestone_reached and line.balance > 0:
            due_by_ccy[line.currency] += line.balance
        rows.append(
            {
                "rule_id": line.rule_id,
                "fee_head": line.fee_head,
                "amount": float(line.amount),
                "currency": line.currency,
                "payable_year_of_study": line.payable_year,
                "payable_term_number": line.payable_term,
                "period_label": _curriculum_label_for_student(
                    student,
                    line.payable_year,
                    line.payable_term,
                    semester_name=line.extra.get("semester_name"),
                ),
                "billing_date": line.extra.get("billing_date"),
                "status": line.status,
                "paid_amount": float(line.paid_amount),
                "balance": float(line.balance),
            }
        )
    return rows, dict(due_by_ccy)


def _student_calendar_type(student: AdmittedStudent) -> str | None:
    program = getattr(student, "admitted_program", None)
    if program is None:
        return None
    return getattr(program, "calendar_type", None)


def _curriculum_label_for_student(
    student: AdmittedStudent,
    year_of_study: int | None,
    term_number: int | None,
    *,
    semester_name: str | None = None,
) -> str:
    from payments.billing_visibility import curriculum_period_label

    return curriculum_period_label(
        year_of_study,
        term_number,
        program=getattr(student, "admitted_program", None),
        calendar_type=_student_calendar_type(student),
        semester_name=semester_name,
    )


def _installment_display(extra: dict[str, Any], student: AdmittedStudent | None = None) -> str:
    """Human-readable instalment / period label for tuition structure rows."""
    inst = extra.get("installment_number")
    if inst:
        return f"Installment {inst}"
    name = (extra.get("semester_name") or "").strip()
    if name:
        return name
    y = extra.get("semester_year_of_study")
    t = extra.get("semester_term_number")
    if y and t:
        if student is not None:
            return _curriculum_label_for_student(student, y, t)
        from payments.billing_visibility import curriculum_period_label

        return curriculum_period_label(y, t)
    order = extra.get("semester_order")
    if order:
        return f"Semester {order}"
    return "—"


def _default_programme_semester_label(student: AdmittedStudent) -> str:
    for rule in _rules_for_student(student):
        if rule.semester_id and rule.semester:
            return rule.semester.name
    return "Programme fees"


def _semester_windows_for_student(student: AdmittedStudent) -> list[tuple]:
    """Unique cohort semesters with date windows, earliest first."""
    from datetime import date as date_cls

    windows: list[tuple] = []
    seen: set[int] = set()
    for rule in _rules_for_student(student):
        sem = rule.semester
        if sem is None or not rule.semester_id or rule.semester_id in seen:
            continue
        start = getattr(sem, "start_date", None)
        if start is None:
            continue
        seen.add(int(rule.semester_id))
        end = getattr(sem, "end_date", None)
        name = (sem.name or "").strip() or f"Semester {sem.order or ''}".strip()
        windows.append((start, end if isinstance(end, date_cls) else end, name))
    windows.sort(key=lambda w: w[0])
    return windows


def _semester_label_for_paid_at(paid_at, student: AdmittedStudent, windows: list[tuple] | None = None) -> str:
    """Map a payment timestamp to the cohort semester that owned that date."""
    from payments.student_payment_allocation import _as_date

    d = _as_date(paid_at)
    wins = windows if windows is not None else _semester_windows_for_student(student)
    if d is None or not wins:
        return _default_programme_semester_label(student)

    for start, end, name in wins:
        if d < start:
            continue
        if end is None or d <= end:
            return name

    if d < wins[0][0]:
        return wins[0][2]

    best = wins[0][2]
    for start, _end, name in wins:
        if start <= d:
            best = name
        else:
            break
    return best


def _payment_history_semester_label(
    payment: StudentTuitionPayment,
    student: AdmittedStudent,
    windows: list[tuple] | None = None,
) -> str:
    if payment.semester_id and payment.semester:
        return payment.semester.name
    rule = payment.fee_plan_rule
    if rule is not None and rule.semester_id and rule.semester:
        return rule.semester.name
    paid_at = payment.paid_at or payment.created_at
    if paid_at:
        return _semester_label_for_paid_at(paid_at, student, windows)
    return _default_programme_semester_label(student)


def _tuition_structure_item_from_line(line, student: AdmittedStudent | None = None) -> dict[str, Any]:
    ex = line.extra
    if line.kind == "scheduled_other":
        period = _curriculum_label_for_student(
            student,
            line.payable_year,
            line.payable_term,
            semester_name=ex.get("semester_name"),
        ) if student is not None else (
            (ex.get("semester_name") or "").strip()
            or f"Year {line.payable_year} Semester {line.payable_term}"
        )
        return {
            "rule_id": line.rule_id,
            "fee_head": line.fee_head,
            "amount": float(line.amount),
            "paid_amount": float(line.paid_amount),
            "balance": float(line.balance),
            "currency": line.currency,
            "semester": {
                "semester_id": ex.get("semester_id"),
                "semester_name": period,
                "program_batch_id": ex.get("program_batch_id"),
                "program_batch_name": ex.get("program_batch_name"),
            },
            "installment_number": None,
            "installment_display": period,
            "due_date_days": None,
            "billing_date": ex.get("billing_date"),
        }
    return {
        "rule_id": line.rule_id,
        "fee_head": line.fee_head,
        "amount": float(line.amount),
        "paid_amount": float(line.paid_amount),
        "balance": float(line.balance),
        "currency": line.currency,
        "semester": {
            "semester_id": ex.get("semester_id"),
            "semester_name": ex.get("semester_name") or "",
            "program_batch_id": ex.get("program_batch_id"),
            "program_batch_name": ex.get("program_batch_name"),
        },
        "installment_number": ex.get("installment_number"),
        "installment_display": _installment_display(ex, student),
        "due_date_days": ex.get("due_date_days"),
        "billing_date": ex.get("billing_date"),
    }


def tuition_structure_dict(student: AdmittedStudent) -> dict:
    alloc = build_finance_allocation(student)
    items = []
    for line in alloc.demand_lines:
        if line.kind not in ("tuition_structure", "scheduled_other"):
            continue
        is_prior = bool(line.extra.get("prior_period_settled"))
        if not is_prior and not _line_is_billable(line):
            continue
        item = _tuition_structure_item_from_line(line, student)
        item["status"] = line.status
        item["prior_term"] = is_prior
        items.append(item)
    batch = student.admitted_batch
    return {
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "pricing": "international" if alloc.international else "local",
        "program": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "batch": batch.name if batch else None,
        "tuition_structure": items,
        "total_required": float(alloc.total_required),
        "total_paid": float(alloc.total_paid),
        "balance": float(alloc.balance),
        "display_currency": alloc.primary_currency,
    }


def _adhoc_charges_for_student(student: AdmittedStudent):
    """Return all non-waived ad-hoc charges for the student."""
    return list(
        StudentTuitionPayment.objects
        .filter(student=student, source='ad_hoc', is_waived=False)
        .select_related('fee_head', 'charged_by', 'semester')
        .order_by('-created_at')
    )


def _finance_totals_from_alloc(alloc, student: AdmittedStudent | None = None) -> dict[str, Any]:
    lifetime = getattr(alloc, "lifetime_paid_by_currency", None) or {}
    primary = alloc.primary_currency
    lifetime_primary = float(lifetime.get(primary, 0) or 0)

    # Displayed % is current-term only (same basis as registration gate).
    # All-terms paid/required/balance still include prior-term carry-forward.
    from payments.student_payment_allocation import tuition_registration_totals

    if student is not None:
        term = tuition_registration_totals(student, current_term_only=True, alloc=alloc)
        percentage_paid = term["percentage_paid"]
        current_term_required = float(term["total_required"] or 0)
        current_term_paid = float(term["total_paid_on_tuition"] or 0)
    else:
        percentage_paid = alloc.percentage_paid
        current_term_required = None
        current_term_paid = None

    return {
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "commitment_paid_ugx": float(alloc.commitment_paid_ugx),
        "commitment_met": alloc.commitment_met,
        "commitment_balance": float(alloc.commitment_balance),
        "total_required": float(alloc.total_required),
        "total_paid": float(alloc.total_paid),
        "balance": float(alloc.balance),
        "percentage_paid": percentage_paid,
        "current_term_required": current_term_required,
        "current_term_paid": current_term_paid,
        "display_currency": alloc.primary_currency,
        "pricing": "international" if alloc.international else "local",
        "tuition_structure_total": float(alloc.tuition_structure_total),
        "ad_hoc_total": float(alloc.ad_hoc_total),
        "ad_hoc_not_yet_due_total": float(alloc.ad_hoc_not_yet_due_total),
        "scheduled_other_fees_due": float(alloc.scheduled_other_due),
        "required_by_currency": {k: float(v) for k, v in alloc.required_by_currency.items()},
        "paid_by_currency": alloc.paid_by_currency,
        # Full SchoolPay + portal history (all semesters), separate from current-term open paid.
        "lifetime_paid": lifetime_primary,
        "lifetime_paid_by_currency": lifetime,
        # Unpaid prior-term balance shown as "Balance carried forward".
        "balance_carried_forward": float(getattr(alloc, "balance_carried_forward", 0) or 0),
        # Surplus after settling prior + currently billable lines (prepaid for next term).
        "prepaid_credit": float(getattr(alloc, "prepaid_credit", 0) or 0),
        "prepaid_credit_by_currency": getattr(alloc, "prepaid_credit_by_currency", None) or {},
    }


def _billing_lines_from_alloc(alloc) -> list[dict[str, Any]]:
    from payments.billing_visibility import curriculum_period_label, period_unit_for_calendar
    from payments.student_payment_allocation import _billing_line_sort_key

    paired: list[tuple] = []
    for line in alloc.demand_lines:
        is_prior = bool(line.extra.get("prior_period_settled"))
        if not is_prior and not _line_is_billable(line):
            continue

        y = line.extra.get("semester_year_of_study") or line.payable_year
        t = line.extra.get("semester_term_number") or line.payable_term
        try:
            yi = int(y) if y is not None else None
            ti = int(t) if t is not None else None
        except (TypeError, ValueError):
            yi, ti = None, None

        cal = line.extra.get("calendar_type") or "semester"
        period_unit = period_unit_for_calendar(cal)
        prior_suffix = f"prior {period_unit.lower()}"
        # Group by curriculum position (Year N Semester/Trimester M) so Room & Board
        # sits under the same accordion as tuition for that period — not a separate "Term" group.
        if yi and ti:
            semester_label = curriculum_period_label(yi, ti, calendar_type=cal)
        else:
            semester_label = curriculum_period_label(
                None,
                None,
                calendar_type=cal,
                semester_name=line.extra.get("semester_name"),
            )

        if line.kind == "tuition_structure":
            ex = line.extra
            batch_name = ex.get("program_batch_name") or ""
            semester_name = ex.get("semester_name") or semester_label
            context = " · ".join(part for part in (batch_name, semester_name) if part)
            if is_prior:
                context = (context + f" · {prior_suffix}").strip(" ·")
            row = {
                "kind": "tuition_structure",
                "rule_id": line.rule_id,
                "fee_head": line.fee_head,
                "description": context or "Programme tuition",
                "amount": float(line.amount),
                "paid_amount": float(line.paid_amount),
                "balance": float(line.balance),
                "currency": line.currency,
                "status": line.status,
                "prior_term": is_prior,
                "year_of_study": yi,
                "term_number": ti,
                "semester_label": semester_label,
            }
        elif line.kind == "scheduled_other":
            desc = line.description or semester_label
            row = {
                "kind": "scheduled_other_fee",
                "rule_id": line.rule_id,
                "fee_head": line.fee_head,
                "description": f"{desc} · {prior_suffix}" if is_prior else desc,
                "amount": float(line.amount),
                "paid_amount": float(line.paid_amount),
                "balance": float(line.balance),
                "currency": line.currency,
                "status": line.status,
                "prior_term": is_prior,
                "year_of_study": yi,
                "term_number": ti,
                "semester_label": semester_label,
            }
        elif line.kind == "ad_hoc":
            if is_prior:
                continue
            row = {
                "kind": "ad_hoc",
                "charge_id": line.charge_id,
                "fee_head": line.fee_head,
                "description": line.description,
                "amount": float(line.amount),
                "paid_amount": float(line.paid_amount),
                "balance": float(line.balance),
                "currency": line.currency,
                "status": line.extra.get("charge_status", line.status),
                "prior_term": False,
                "year_of_study": yi,
                "term_number": ti,
                "semester_label": "Ad-hoc charges",
            }
        else:
            continue
        paired.append((line, row))

    paired.sort(key=lambda item: _billing_line_sort_key(item[0]))
    return [row for _line, row in paired]


def student_finance_totals(student: AdmittedStudent) -> dict[str, Any]:
    """Programme billing totals (payments pooled; credit applied tuition → other → ad-hoc)."""
    alloc = build_finance_allocation(student)
    return _finance_totals_from_alloc(alloc, student)


def student_billing_lines(student: AdmittedStudent) -> list[dict[str, Any]]:
    """Fee lines with allocated paid/balance from the shared payment pool."""
    return _billing_lines_from_alloc(build_finance_allocation(student))


def student_finance_bundle(student: AdmittedStudent) -> dict[str, Any]:
    """Totals + fee lines from one allocation (Bonafide / admin snapshots)."""
    alloc = build_finance_allocation(student)
    return {
        "totals": _finance_totals_from_alloc(alloc, student),
        "lines": _billing_lines_from_alloc(alloc),
    }


def registration_card_payment_history(
    student: AdmittedStudent, *, limit: int = 12
) -> list[dict[str, Any]]:
    """
    Compact completed-payment rows for the printed registration card (A4).
    Excludes pending/failed/waived and scholarship ledger credits.
    Includes all semesters; each row is labeled by payment date → cohort semester.
    """
    rows: list[dict[str, Any]] = []
    windows = _semester_windows_for_student(student)

    for row in (
        tuition_ledger_queryset_for_student(student)
        .filter(transaction_completion_status="Completed")
        .order_by("-payment_date_time")[:80]
    ):
        paid_at = row.payment_date_time
        raw = row.raw_response if isinstance(row.raw_response, dict) else {}
        is_manual = (row.schoolpay_receipt_number or "").startswith("BANK-") or (
            raw.get("source") == "manual_bank_reconciliation"
        )
        rows.append(
            {
                "id": row.id,
                "paid_at": paid_at.isoformat() if paid_at else None,
                "amount": float(row.amount or 0),
                "currency": "UGX",
                "channel": (row.source_payment_channel or "SchoolPay").strip() or "SchoolPay",
                "receipt": (row.schoolpay_receipt_number or "").strip(),
                "description": (row.source_channel_trans_detail or "Tuition payment").strip()
                or "Tuition payment",
                "semester": _semester_label_for_paid_at(paid_at, student, windows),
                "is_manual_bank": is_manual,
                "bank_reference": (row.source_channel_transaction_id or raw.get("bank_reference") or ""),
                "bank_name": (row.settlement_bank_code or raw.get("bank_name") or ""),
                "notes": (raw.get("notes") or ""),
            }
        )

    for p in (
        StudentTuitionPayment.objects.filter(
            student=student,
            status="completed",
            is_waived=False,
        )
        .exclude(source="scholarship")
        .select_related("fee_plan_rule__fee_head", "fee_plan_rule__semester", "fee_head", "semester")
        .order_by("-paid_at", "-created_at")[:80]
    ):
        paid_at = p.paid_at or p.created_at
        channel = (p.payment_method or "").replace("_", " ").strip() or "Portal"
        if p.source == "ad_hoc":
            desc = (p.label or (p.fee_head.name if p.fee_head_id else "Charge")).strip()
        else:
            desc = "Tuition"
            if p.fee_plan_rule_id and p.fee_plan_rule and p.fee_plan_rule.fee_head_id:
                desc = p.fee_plan_rule.fee_head.name
        rows.append(
            {
                "paid_at": paid_at.isoformat() if paid_at else None,
                "amount": float(p.amount or 0),
                "currency": (p.currency or "UGX").strip() or "UGX",
                "channel": channel.title() if channel else "Portal",
                "receipt": (p.receipt_number or p.payment_reference or "").strip(),
                "description": desc or "Payment",
                "semester": _payment_history_semester_label(p, student, windows),
            }
        )

    # Deduplicate by receipt+amount+date when SchoolPay also mirrored as portal row
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for r in sorted(rows, key=lambda h: h.get("paid_at") or "", reverse=True):
        key = f"{r.get('receipt')}|{r.get('amount')}|{(r.get('paid_at') or '')[:10]}"
        if r.get("receipt") and key in seen:
            continue
        if r.get("receipt"):
            seen.add(key)
        unique.append(r)
        if len(unique) >= limit:
            break
    return unique


def payment_status_dict(student: AdmittedStudent, request=None) -> dict:
    totals = student_finance_totals(student)
    other_fee_rows, _ = other_schedule_rows_and_due_by_currency(student)
    adhoc_charges = _adhoc_charges_for_student(student)

    windows = _semester_windows_for_student(student)
    history = []
    for row in tuition_ledger_queryset_for_student(student).filter(
        transaction_completion_status="Completed"
    ).order_by("-payment_date_time")[:100]:
        paid_at = row.payment_date_time
        history.append(
            {
                "id": row.id,
                "source": "schoolpay",
                "amount": float(row.amount),
                "currency": "UGX",
                "status": "completed",
                "payment_method": row.source_payment_channel or "SchoolPay",
                "fee_head": "Tuition payment",
                "semester": _semester_label_for_paid_at(paid_at, student, windows),
                "paid_at": paid_at.isoformat() if paid_at else None,
                "receipt_number": row.schoolpay_receipt_number or "",
                "is_waived": False,
                "label": row.source_channel_trans_detail or "",
                "is_manual_bank": (
                    (row.schoolpay_receipt_number or "").startswith("BANK-")
                    or (
                        isinstance(row.raw_response, dict)
                        and row.raw_response.get("source") == "manual_bank_reconciliation"
                    )
                ),
            }
        )
    for p in StudentTuitionPayment.objects.filter(student=student).select_related(
        "fee_plan_rule__fee_head",
        "fee_plan_rule__semester",
        "fee_head",
        "semester",
        "charged_by",
    ).order_by("-created_at")[:100]:
        if p.source == 'ad_hoc':
            fh = p.fee_head.name if p.fee_head_id else "Ad-hoc charge"
            lbl = p.label or fh
        else:
            fh = ""
            if p.fee_plan_rule and p.fee_plan_rule.fee_head:
                fh = p.fee_plan_rule.fee_head.name
            lbl = fh or "Tuition"
        history.append(
            {
                "id":             p.id,
                "source":         p.source,
                "amount":         float(p.amount),
                "currency":       p.currency or "UGX",
                "status":         p.status,
                "payment_method": p.payment_method or "",
                "fee_head":       lbl,
                "semester":       _payment_history_semester_label(p, student, windows),
                "paid_at":        p.paid_at.isoformat() if p.paid_at else None,
                "receipt_number": p.receipt_number or "",
                "is_waived":      p.is_waived,
                "label":          p.label or "",
            }
        )

    history.sort(key=lambda h: h.get("paid_at") or "", reverse=True)

    # Separate ad-hoc outstanding charges for the student's charges section. A pending
    # charge tagged to a future semester (e.g. a course-exemption fee split onto "Year 2
    # Term 1") isn't due yet, so it's held back from this list the same way future
    # tuition/scheduled fees are — it reappears once that term's billing date arrives.
    from payments.billing_visibility import adhoc_charge_billing_reached

    adhoc_list = [
        {
            "id":            c.id,
            "fee_head_name": c.fee_head.name if c.fee_head_id else "Charge",
            "fee_head_category": c.fee_head.category if c.fee_head_id else "other",
            "label":         c.label,
            "amount":        float(c.amount),
            "currency":      c.currency or "UGX",
            "status":        c.status,
            "is_waived":     c.is_waived,
            "charged_by":    c.charged_by.get_full_name() if c.charged_by_id else None,
            "created_at":    c.created_at.isoformat(),
        }
        for c in adhoc_charges
        if c.status != "pending" or adhoc_charge_billing_reached(c)
    ]

    from admissions.temporary_access import student_temporary_access

    return {
        **totals,
        "payment_history": history,
        "ad_hoc_charges": adhoc_list,
        "scheduled_other_fees": other_fee_rows,
        "scheduled_other_fees_total_due": totals["scheduled_other_fees_due"],
        "billing_lines": student_billing_lines(student),
        "payment_code": student.student_id,
        "temporary_access": student_temporary_access(student, request=request),
        **offer_letter_portal_fields(student, request),
    }
