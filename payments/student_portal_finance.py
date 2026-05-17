"""Student portal: tuition lines (FeePlanRule) and payment totals for semester billing."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

COMMITMENT_FEE_THRESHOLD = Decimal("150000")

from django.db.models import Q
from admissions.models import AdmittedStudent

from payments.batch_semester_fee_helpers import get_or_create_tuition_fee_plan
from payments.models import FeePlanRule, StudentTuitionPayment
from payments.other_fee_schedule_views import get_or_create_other_schedule_fee_plan
from payments.student_fee_pricing import (
    effective_amount_currency,
    is_international_student,
    paid_by_currency,
    required_by_currency,
)


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
    """
    Cohort for fee rules: enrollment → intended at admit → default offer cohort
    → sole cohort with a semester tuition matrix (legacy records).
    """
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


def _completed_amount_for_fee_plan_rule(student: AdmittedStudent, rule: FeePlanRule, currency: str) -> Decimal:
    ccy = (currency or "UGX").upper()
    total = Decimal("0")
    for p in StudentTuitionPayment.objects.filter(
        student=student,
        fee_plan_rule_id=rule.id,
        status="completed",
        is_waived=False,
    ):
        if (p.currency or "UGX").upper() == ccy:
            total += p.amount or Decimal("0")
    return total


def completed_commitment_paid_ugx(student: AdmittedStudent) -> Decimal:
    total = Decimal("0")
    for payment in StudentTuitionPayment.objects.filter(student=student, status="completed"):
        if (payment.currency or "UGX").upper() == "UGX":
            total += payment.amount or Decimal("0")
    return total


def commitment_payment_summary(student: AdmittedStudent) -> dict[str, float | bool]:
    paid = completed_commitment_paid_ugx(student)
    threshold = COMMITMENT_FEE_THRESHOLD
    balance = max(threshold - paid, Decimal("0"))
    met = paid >= threshold
    return {
        "commitment_threshold": float(threshold),
        "commitment_paid_ugx": float(paid),
        "commitment_met": met,
        "commitment_balance": float(balance),
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
    pdf_url = offer_letter_pdf_url(student, request) if eligible and has_pdf else None
    return {
        **summary,
        "offer_letter_eligible": eligible,
        "offer_letter_pdf_url": pdf_url,
        "offer_letter_can_download": bool(eligible and has_pdf),
    }


def other_schedule_rows_and_due_by_currency(student: AdmittedStudent, intl: bool) -> tuple[list[dict[str, Any]], dict[str, Decimal]]:
    cy, ct = _student_curriculum_year_term(student)
    rows: list[dict[str, Any]] = []
    due_by_ccy: dict[str, Decimal] = defaultdict(Decimal)
    for rule in _applicable_other_schedule_rules(student):
        py = int(rule.payable_year_of_study)
        pt = int(rule.payable_term_number)
        reached = _milestone_reached(cy, ct, py, pt)
        amt, cur = effective_amount_currency(rule, intl)
        paid = _completed_amount_for_fee_plan_rule(student, rule, cur)
        bal = max(amt - paid, Decimal("0"))
        if reached and bal > 0:
            due_by_ccy[cur] += bal
        if reached:
            if bal <= 0:
                st = "paid"
            else:
                st = "due"
        else:
            st = "not_due"
        rows.append(
            {
                "rule_id": rule.id,
                "fee_head": rule.fee_head.name if rule.fee_head_id else "",
                "amount": float(amt),
                "currency": cur,
                "payable_year_of_study": py,
                "payable_term_number": pt,
                "status": st,
                "paid_amount": float(paid),
                "balance": float(bal),
            }
        )
    return rows, dict(due_by_ccy)


def tuition_structure_dict(student: AdmittedStudent) -> dict:
    rules = _rules_for_student(student)
    intl = is_international_student(student)
    items = []
    for r in rules:
        amt, cur = effective_amount_currency(r, intl)
        items.append(
            {
                "rule_id": r.id,
                "fee_head": r.fee_head.name if r.fee_head_id else "",
                "amount": float(amt),
                "currency": cur,
                "semester": {
                    "semester_id": r.semester_id,
                    "semester_name": r.semester.name if r.semester_id else "",
                    "program_batch_id": r.program_batch_id,
                    "program_batch_name": r.program_batch.name if r.program_batch_id else None,
                },
                "installment_number": r.installment_number,
                "due_date_days": r.due_date_days,
            }
        )
    for r in _applicable_other_schedule_rules(student):
        amt, cur = effective_amount_currency(r, intl)
        py = int(r.payable_year_of_study)
        pt = int(r.payable_term_number)
        items.append(
            {
                "rule_id": r.id,
                "fee_head": r.fee_head.name if r.fee_head_id else "",
                "amount": float(amt),
                "currency": cur,
                "semester": {
                    "semester_id": None,
                    "semester_name": f"Year {py}, Term {pt} (scheduled fee)",
                    "program_batch_id": r.program_batch_id,
                    "program_batch_name": r.program_batch.name if r.program_batch_id else None,
                },
                "installment_number": None,
                "due_date_days": None,
            }
        )
    req_by = required_by_currency(rules, intl)
    _, other_due = other_schedule_rows_and_due_by_currency(student, intl)
    for ccy, amt in other_due.items():
        req_by[ccy] = req_by.get(ccy, Decimal("0")) + amt
    if req_by:
        primary_ccy = max(req_by.keys(), key=lambda k: float(req_by[k]))
        total_display = float(req_by[primary_ccy])
    else:
        primary_ccy = "USD" if intl else "UGX"
        total_display = 0.0
    batch = student.admitted_batch
    return {
        "student_id": student.student_id,
        "reg_no": student.reg_no,
        "pricing": "international" if intl else "local",
        "program": student.admitted_program.name if student.admitted_program_id else None,
        "campus": student.admitted_campus.name if student.admitted_campus_id else None,
        "batch": batch.name if batch else None,
        "tuition_structure": items,
        "total_required": total_display,
        "display_currency": primary_ccy,
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
    """Programme billing totals for a student (structure + scheduled fees + ad-hoc)."""
    rules = _rules_for_student(student)
    intl = is_international_student(student)
    req_by = required_by_currency(rules, intl)
    other_fee_rows, other_due_by_ccy = other_schedule_rows_and_due_by_currency(student, intl)
    for ccy, amt in other_due_by_ccy.items():
        req_by[ccy] = req_by.get(ccy, Decimal("0")) + amt
    paid_by = paid_by_currency(student)
    primary_ccy = max(req_by.keys(), key=lambda k: float(req_by[k])) if req_by else ("USD" if intl else "UGX")
    total_required = req_by.get(primary_ccy, Decimal("0")) if req_by else Decimal("0")

    adhoc_charges = _adhoc_charges_for_student(student)
    adhoc_required = sum(
        c.amount for c in adhoc_charges
        if c.status in ("pending", "completed") and (c.currency or "UGX").upper() == primary_ccy
    )
    total_required_with_adhoc = total_required + adhoc_required

    paid_primary = paid_by.get(primary_ccy, Decimal("0"))
    total_paid = float(paid_primary)
    tr = float(total_required_with_adhoc)
    balance = max(tr - total_paid, 0.0)
    pct = (total_paid / tr * 100.0) if tr > 0 else 0.0
    scheduled_other_fees_due = sum(
        Decimal(str(row["balance"]))
        for row in other_fee_rows
        if row.get("status") == "due" and (row.get("currency") or "").upper() == primary_ccy
    )

    return {
        **commitment_payment_summary(student),
        "total_required": tr,
        "total_paid": total_paid,
        "balance": balance,
        "percentage_paid": round(pct, 1),
        "display_currency": primary_ccy,
        "pricing": "international" if intl else "local",
        "tuition_structure_total": float(total_required),
        "ad_hoc_total": float(adhoc_required),
        "scheduled_other_fees_due": float(scheduled_other_fees_due),
        "required_by_currency": {k: float(v) for k, v in req_by.items()},
        "paid_by_currency": {k: float(v) for k, v in paid_by.items()},
    }


def student_billing_lines(student: AdmittedStudent) -> list[dict[str, Any]]:
    """Fee lines from programme structure, scheduled other fees, and ad-hoc charges."""
    intl = is_international_student(student)
    lines: list[dict[str, Any]] = []

    for rule in _rules_for_student(student):
        amt, cur = effective_amount_currency(rule, intl)
        paid = _completed_amount_for_fee_plan_rule(student, rule, cur)
        bal = max(amt - paid, Decimal("0"))
        semester_name = rule.semester.name if rule.semester_id else ""
        batch_name = rule.program_batch.name if rule.program_batch_id else ""
        context = " · ".join(part for part in (batch_name, semester_name) if part)
        lines.append(
            {
                "kind": "tuition_structure",
                "rule_id": rule.id,
                "fee_head": rule.fee_head.name if rule.fee_head_id else "Tuition",
                "description": context or "Programme tuition",
                "amount": float(amt),
                "paid_amount": float(paid),
                "balance": float(bal),
                "currency": cur,
                "status": "paid" if bal <= 0 else "due",
            }
        )

    for row in other_schedule_rows_and_due_by_currency(student, intl)[0]:
        lines.append(
            {
                "kind": "scheduled_other_fee",
                "rule_id": row["rule_id"],
                "fee_head": row["fee_head"],
                "description": (
                    f"Year {row['payable_year_of_study']}, "
                    f"Term {row['payable_term_number']}"
                ),
                "amount": row["amount"],
                "paid_amount": row["paid_amount"],
                "balance": row["balance"],
                "currency": row["currency"],
                "status": row["status"],
            }
        )

    for charge in _adhoc_charges_for_student(student):
        cur = (charge.currency or "UGX").upper()
        paid = float(charge.amount) if charge.status == "completed" else 0.0
        amount = float(charge.amount)
        bal = 0.0 if charge.status == "completed" else amount
        period = ""
        if charge.semester_id and charge.semester:
            sem = charge.semester
            if sem.year_of_study and sem.term_number:
                period = f"Year {sem.year_of_study}, Term {sem.term_number}"
            else:
                period = sem.name
        base_desc = charge.label or (charge.fee_head.name if charge.fee_head_id else "Charge")
        description = f"{base_desc} ({period})" if period else base_desc
        lines.append(
            {
                "kind": "ad_hoc",
                "charge_id": charge.id,
                "fee_head": charge.fee_head.name if charge.fee_head_id else "Ad-hoc charge",
                "description": description,
                "amount": amount,
                "paid_amount": paid,
                "balance": bal,
                "currency": cur,
                "status": charge.status,
            }
        )

    return lines

def payment_status_dict(student: AdmittedStudent, request=None) -> dict:
    totals = student_finance_totals(student)
    other_fee_rows, _ = other_schedule_rows_and_due_by_currency(
        student,
        totals["pricing"] == "international",
    )
    adhoc_charges = _adhoc_charges_for_student(student)

    history = []
    for p in StudentTuitionPayment.objects.filter(student=student).select_related(
        "fee_plan_rule__fee_head", "fee_head", "semester", "charged_by"
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
                "semester":       p.semester.name if p.semester_id else "",
                "paid_at":        p.paid_at.isoformat() if p.paid_at else None,
                "receipt_number": p.receipt_number or "",
                "is_waived":      p.is_waived,
                "label":          p.label or "",
            }
        )

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
