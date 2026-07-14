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
                "billing_date": line.extra.get("billing_date"),
                "status": line.status,
                "paid_amount": float(line.paid_amount),
                "balance": float(line.balance),
            }
        )
    return rows, dict(due_by_ccy)


def _installment_display(extra: dict[str, Any]) -> str:
    """Human-readable instalment / term label for tuition structure rows."""
    inst = extra.get("installment_number")
    if inst:
        return f"Installment {inst}"
    y = extra.get("semester_year_of_study")
    t = extra.get("semester_term_number")
    if y and t:
        return f"Year {y}, Term {t}"
    order = extra.get("semester_order")
    if order:
        return f"Semester {order}"
    name = (extra.get("semester_name") or "").strip()
    return name or "—"

def _default_programme_semester_label(student: AdmittedStudent) -> str:
    for rule in _rules_for_student(student):
        if rule.semester_id and rule.semester:
            return rule.semester.name
    return "Programme fees"


def _payment_history_semester_label(payment: StudentTuitionPayment, student: AdmittedStudent) -> str:
    if payment.semester_id and payment.semester:
        return payment.semester.name
    rule = payment.fee_plan_rule
    if rule is not None and rule.semester_id and rule.semester:
        return rule.semester.name
    if payment.source == "ad_hoc" and payment.semester_id and payment.semester:
        return payment.semester.name
    return _default_programme_semester_label(student)


def _tuition_structure_item_from_line(line) -> dict[str, Any]:
    ex = line.extra
    if line.kind == "scheduled_other":
        sem_name = f"Year {line.payable_year}, Term {line.payable_term} (scheduled fee)"
        inst_label = f"Year {line.payable_year}, Term {line.payable_term}"
        return {
            "rule_id": line.rule_id,
            "fee_head": line.fee_head,
            "amount": float(line.amount),
            "paid_amount": float(line.paid_amount),
            "balance": float(line.balance),
            "currency": line.currency,
            "semester": {
                "semester_id": None,
                "semester_name": sem_name,
                "program_batch_id": ex.get("program_batch_id"),
                "program_batch_name": ex.get("program_batch_name"),
            },
            "installment_number": None,
            "installment_display": inst_label,
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
        "installment_display": _installment_display(ex),
        "due_date_days": ex.get("due_date_days"),
        "billing_date": ex.get("billing_date"),
    }


def tuition_structure_dict(student: AdmittedStudent) -> dict:
    alloc = build_finance_allocation(student)
    items = [
        _tuition_structure_item_from_line(line)
        for line in alloc.demand_lines
        if line.kind in ("tuition_structure", "scheduled_other")
        and _line_is_billable(line)
    ]
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


def student_finance_totals(student: AdmittedStudent) -> dict[str, Any]:
    """Programme billing totals (payments pooled; credit applied tuition → other → ad-hoc)."""
    alloc = build_finance_allocation(student)
    return {
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "commitment_paid_ugx": float(alloc.commitment_paid_ugx),
        "commitment_met": alloc.commitment_met,
        "commitment_balance": float(alloc.commitment_balance),
        "total_required": float(alloc.total_required),
        "total_paid": float(alloc.total_paid),
        "balance": float(alloc.balance),
        "percentage_paid": alloc.percentage_paid,
        "display_currency": alloc.primary_currency,
        "pricing": "international" if alloc.international else "local",
        "tuition_structure_total": float(alloc.tuition_structure_total),
        "ad_hoc_total": float(alloc.ad_hoc_total),
        "scheduled_other_fees_due": float(alloc.scheduled_other_due),
        "required_by_currency": {k: float(v) for k, v in alloc.required_by_currency.items()},
        "paid_by_currency": alloc.paid_by_currency,
    }


def student_billing_lines(student: AdmittedStudent) -> list[dict[str, Any]]:
    """Fee lines with allocated paid/balance from the shared payment pool."""
    alloc = build_finance_allocation(student)
    lines: list[dict[str, Any]] = []
    for line in alloc.demand_lines:
        if not _line_is_billable(line):
            continue
        if line.kind == "tuition_structure":
            ex = line.extra
            batch_name = ex.get("program_batch_name") or ""
            semester_name = ex.get("semester_name") or ""
            context = " · ".join(part for part in (batch_name, semester_name) if part)
            lines.append(
                {
                    "kind": "tuition_structure",
                    "rule_id": line.rule_id,
                    "fee_head": line.fee_head,
                    "description": context or "Programme tuition",
                    "amount": float(line.amount),
                    "paid_amount": float(line.paid_amount),
                    "balance": float(line.balance),
                    "currency": line.currency,
                    "status": line.status,
                }
            )
        elif line.kind == "scheduled_other":
            lines.append(
                {
                    "kind": "scheduled_other_fee",
                    "rule_id": line.rule_id,
                    "fee_head": line.fee_head,
                    "description": line.description,
                    "amount": float(line.amount),
                    "paid_amount": float(line.paid_amount),
                    "balance": float(line.balance),
                    "currency": line.currency,
                    "status": line.status,
                }
            )
        elif line.kind == "ad_hoc":
            lines.append(
                {
                    "kind": "ad_hoc",
                    "charge_id": line.charge_id,
                    "fee_head": line.fee_head,
                    "description": line.description,
                    "amount": float(line.amount),
                    "paid_amount": float(line.paid_amount),
                    "balance": float(line.balance),
                    "currency": line.currency,
                    "status": line.extra.get("charge_status", line.status),
                }
            )
    return lines

def payment_status_dict(student: AdmittedStudent, request=None) -> dict:
    totals = student_finance_totals(student)
    other_fee_rows, _ = other_schedule_rows_and_due_by_currency(student)
    adhoc_charges = _adhoc_charges_for_student(student)

    default_semester = _default_programme_semester_label(student)
    history = []
    for row in tuition_ledger_queryset_for_student(student).filter(
        transaction_completion_status="Completed"
    ).order_by("-payment_date_time")[:50]:
        history.append(
            {
                "id": row.id,
                "source": "schoolpay",
                "amount": float(row.amount),
                "currency": "UGX",
                "status": "completed",
                "payment_method": row.source_payment_channel or "SchoolPay",
                "fee_head": "Tuition payment",
                "semester": default_semester,
                "paid_at": row.payment_date_time.isoformat() if row.payment_date_time else None,
                "receipt_number": row.schoolpay_receipt_number or "",
                "is_waived": False,
                "label": row.source_channel_trans_detail or "",
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
                "semester":       _payment_history_semester_label(p, student),
                "paid_at":        p.paid_at.isoformat() if p.paid_at else None,
                "receipt_number": p.receipt_number or "",
                "is_waived":      p.is_waived,
                "label":          p.label or "",
            }
        )

    history.sort(key=lambda h: h.get("paid_at") or "", reverse=True)

    # Separate ad-hoc outstanding charges for the student's charges section
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
    ]

    return {
        **totals,
        "payment_history": history,
        "ad_hoc_charges": adhoc_list,
        "scheduled_other_fees": other_fee_rows,
        "scheduled_other_fees_total_due": totals["scheduled_other_fees_due"],
        "billing_lines": student_billing_lines(student),
        "payment_code": student.student_id,
        **offer_letter_portal_fields(student, request),
    }
