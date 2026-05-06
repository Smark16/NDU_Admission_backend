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
    if not program:
        return []
    fee_plan = get_or_create_tuition_fee_plan(program)
    enrollment = getattr(student, "programme_enrollment", None)
    current_program_batch_id = getattr(enrollment, "program_batch_id", None)

    qs = FeePlanRule.objects.filter(
            fee_plan=fee_plan,
            is_active=True,
            semester__isnull=False,
            program_batch__program_id=program.id,
            payable_year_of_study__isnull=True,
            payable_term_number__isnull=True,
        )
    if current_program_batch_id:
        qs = qs.filter(program_batch_id=current_program_batch_id)
    return list(
        qs
        .select_related("fee_head", "program_batch", "semester")
        .order_by("program_batch_id", "semester_id", "order")
    )


def _scheduled_other_fee_rules_for_student(student: AdmittedStudent):
    """Rules for non-semester milestone fees due at a specific year/term."""
    from django.db.models import Q

    program = student.admitted_program
    if not program:
        return []

    enrollment = getattr(student, "programme_enrollment", None)
    current_program_batch_id = getattr(enrollment, "program_batch_id", None)

    rules_qs = (
        FeePlanRule.objects.filter(
            is_active=True,
            payable_year_of_study__isnull=False,
            payable_term_number__isnull=False,
        )
        .filter(
            Q(fee_plan__program=program)
            | Q(fee_plan__programs=program)
            | Q(program=program)
        )
        .exclude(
            Q(fee_head__code__iexact="TUITION_FEE")
            | Q(fee_head__code__iexact="FUNCTIONAL_FEE")
        )
        .select_related("fee_head", "fee_plan", "program_batch", "semester")
        .distinct()
        .order_by("payable_year_of_study", "payable_term_number", "order", "id")
    )
    if current_program_batch_id:
        rules_qs = rules_qs.filter(
            Q(program_batch_id=current_program_batch_id) | Q(program_batch__isnull=True)
        )
    else:
        rules_qs = rules_qs.filter(program_batch__isnull=True)

    ordered_rules = sorted(
        list(rules_qs),
        key=lambda r: (
            int(r.payable_year_of_study or 0),
            int(r.payable_term_number or 0),
            0 if (current_program_batch_id and r.program_batch_id == current_program_batch_id) else 1,
            int(r.order or 0),
            int(r.id or 0),
        ),
    )
    deduped_rules = []
    seen = set()
    for r in ordered_rules:
        key = (r.fee_head_id, int(r.payable_year_of_study or 0), int(r.payable_term_number or 0))
        if key in seen:
            continue
        seen.add(key)
        deduped_rules.append(r)

    current_year = int(getattr(enrollment, "current_year_of_study", 1) or 1)
    current_term = int(getattr(enrollment, "current_term_number", 1) or 1)
    intl = is_international_student(student)

    out = []
    for r in deduped_rules:
        required_amt, required_ccy = effective_amount_currency(r, intl)
        if required_amt <= 0:
            continue

        paid_amt = Decimal("0")
        paid_qs = StudentTuitionPayment.objects.filter(
            student=student,
            fee_plan_rule=r,
            status="completed",
            is_waived=False,
        )
        for p in paid_qs:
            if (p.currency or "UGX").strip().upper() == required_ccy:
                paid_amt += (p.amount or Decimal("0"))

        due_pos = (int(r.payable_year_of_study), int(r.payable_term_number))
        cur_pos = (current_year, current_term)
        reached_due = cur_pos >= due_pos
        settled = paid_amt >= required_amt

        if settled:
            state = "paid"
        elif reached_due:
            state = "due"
        else:
            state = "not_due"

        out.append(
            {
                "rule_id": r.id,
                "fee_plan_name": r.fee_plan.name if r.fee_plan_id else "",
                "fee_head": r.fee_head.name if r.fee_head_id else "Other fee",
                "amount": float(required_amt),
                "currency": required_ccy,
                "payable_year_of_study": int(r.payable_year_of_study),
                "payable_term_number": int(r.payable_term_number),
                "status": state,
                "paid_amount": float(paid_amt),
                "balance": float(max(required_amt - paid_amt, Decimal("0"))),
            }
        )
    return out


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
    scheduled_other_fees = _scheduled_other_fee_rules_for_student(student)
    scheduled_due_required = sum(
        Decimal(str(x["amount"]))
        for x in scheduled_other_fees
        if x["currency"] == primary_ccy and x["status"] in ("due", "paid")
    )
    total_required_with_adhoc = total_required + adhoc_required + scheduled_due_required

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
            student=student,
            status="completed",
            is_waived=False,
            fee_plan_rule__isnull=False,
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
        "scheduled_other_fees": scheduled_other_fees,
        "scheduled_other_fees_total_due": float(scheduled_due_required),
        # --- tuition payment / SchoolPay fields ---
        "payment_code": student.schoolpay_code or student.reg_no,  # stable SchoolPay reference
        "schoolpay_code": student.schoolpay_code or student.reg_no,
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "commitment_met": commitment_met,
        "commitment_paid_ugx": float(completed_ugx),
    }
