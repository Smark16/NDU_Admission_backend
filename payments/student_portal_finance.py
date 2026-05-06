"""Student portal: tuition lines (FeePlanRule) and payment totals for semester billing."""
from decimal import Decimal

# Commitment fee threshold: once total valid tuition payments reach this amount,
# the student's academic enrollment can be activated.  Hardcoded for now;
# can be surfaced into RegistrationSettings later.
COMMITMENT_FEE_THRESHOLD = Decimal("150000")

from django.db.models import Q
from admissions.models import AdmittedStudent

from payments.batch_semester_fee_helpers import get_or_create_tuition_fee_plan
from payments.models import FeePlanRule, StudentTuitionPayment
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
            "admitted_program", "admitted_campus", "admitted_batch", "application"
        )
        .filter(
            Q(application__applicant=user)
            | Q(student_user=user)
            | Q(reg_no=user.username),
            is_admitted=True,
        )
        .first()
    )


def _rules_for_student(student: AdmittedStudent):
    from .feeplanrule_table import ensure_feeplanrule_table

    ensure_feeplanrule_table()
    program = student.admitted_program
    fee_plan = get_or_create_tuition_fee_plan(program)
    return list(
        FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            program_batch__program_id=program.id,
        )
        .select_related("fee_head", "program_batch", "semester")
        .order_by("program_batch_id", "semester_id", "order")
    )


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
    req_by = required_by_currency(rules, intl)
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
        .select_related('fee_head', 'charged_by')
        .order_by('-created_at')
    )


def payment_status_dict(student: AdmittedStudent) -> dict:
    rules = _rules_for_student(student)
    intl = is_international_student(student)
    req_by = required_by_currency(rules, intl)
    paid_by = paid_by_currency(student)
    primary_ccy = max(req_by.keys(), key=lambda k: float(req_by[k])) if req_by else ("USD" if intl else "UGX")
    total_required = req_by.get(primary_ccy, Decimal("0")) if req_by else Decimal("0")

    # Add active ad-hoc charges (pending + completed, not waived) to the required total
    adhoc_charges = _adhoc_charges_for_student(student)
    adhoc_required = sum(
        c.amount for c in adhoc_charges
        if c.status in ('pending', 'completed') and (c.currency or "UGX").upper() == primary_ccy
    )
    total_required_with_adhoc = total_required + adhoc_required

    paid_primary = paid_by.get(primary_ccy, Decimal("0"))
    total_paid = float(paid_primary)
    tr = float(total_required_with_adhoc)
    balance = max(tr - total_paid, 0.0)
    pct = (total_paid / tr * 100.0) if tr > 0 else 0.0

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

    # Commitment fee: check cumulative completed UGX payments (or primary currency)
    completed_ugx = sum(
        p.amount
        for p in StudentTuitionPayment.objects.filter(
            student=student, status="completed"
        )
        if (p.currency or "UGX").upper() == "UGX"
    )
    commitment_met = completed_ugx >= COMMITMENT_FEE_THRESHOLD

    return {
        "total_required": tr,
        "total_paid": total_paid,
        "balance": balance,
        "percentage_paid": round(pct, 1),
        "display_currency": primary_ccy,
        "pricing": "international" if intl else "local",
        "required_by_currency": {k: float(v) for k, v in req_by.items()},
        "paid_by_currency": {k: float(v) for k, v in paid_by.items()},
        "payment_history": history,
        "ad_hoc_charges": adhoc_list,
        "ad_hoc_total": float(adhoc_required),
        # --- tuition payment / SchoolPay fields ---
        "payment_code": student.reg_no,          # student's stable SchoolPay reference
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "commitment_met": commitment_met,
        "commitment_paid_ugx": float(completed_ugx),
    }
