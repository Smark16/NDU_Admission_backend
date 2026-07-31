"""Auto ad-hoc retake / missed-paper fees on registration."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Q

from admissions.models import AdmittedStudent
from Programs.models import StudentCourseUnitEnrollment

from .models import FeeHead, FeePlanRule, StudentTuitionPayment
from .student_fee_pricing import effective_amount_currency, is_international_student

DEFAULT_RETAKE_FEE_UGX = Decimal("50000")
RETAKE_FEE_HEAD_CODE = "RETAKE_FEE"


def get_or_create_retake_fee_head() -> FeeHead:
    head, _ = FeeHead.objects.get_or_create(
        code=RETAKE_FEE_HEAD_CODE,
        defaults={
            "name": "Retake / Resit Fee",
            "category": "retake",
            "description": "Fee charged when registering a retake or missed paper.",
            "is_active": True,
        },
    )
    return head


def _program_rule_q(program) -> Q:
    return Q(program_id=program.id) | Q(program__isnull=True, fee_plan__program_id=program.id)


def resolve_retake_fee_amount(
    student: AdmittedStudent,
) -> tuple[Decimal, str, FeeHead]:
    """Amount/currency from programme course_retake FeePlanRule, else default UGX."""
    head = get_or_create_retake_fee_head()
    intl = is_international_student(student)
    program = getattr(student, "admitted_program", None)
    if program is not None:
        rule = (
            FeePlanRule.objects.filter(
                is_active=True,
                trigger_stage="course_retake",
                fee_head=head,
            )
            .filter(_program_rule_q(program))
            .order_by("order", "id")
            .first()
        )
        if rule is None:
            rule = (
                FeePlanRule.objects.filter(
                    is_active=True,
                    trigger_stage="course_retake",
                    fee_head__category="retake",
                )
                .filter(_program_rule_q(program))
                .select_related("fee_head")
                .order_by("order", "id")
                .first()
            )
        if rule is not None:
            amt, cur = effective_amount_currency(rule, intl)
            if amt > 0:
                return amt, cur, rule.fee_head or head
    return DEFAULT_RETAKE_FEE_UGX, "UGX", head


def preview_retake_fee(student: AdmittedStudent) -> dict[str, Any]:
    amt, cur, head = resolve_retake_fee_amount(student)
    return {
        "amount": float(amt),
        "currency": cur,
        "fee_head": head.name,
        "fee_head_code": head.code,
    }


def _idempotency_token(enrollment_id: int) -> str:
    return f"retake_enrollment_id={enrollment_id}"


def ensure_retake_fee_for_enrollment(
    student: AdmittedStudent,
    enrollment: StudentCourseUnitEnrollment,
    *,
    charged_by=None,
    registration_kind: str | None = None,
) -> StudentTuitionPayment | None:
    """
    Create a pending ad-hoc retake charge once per enrollment.
    Returns existing charge if already created.
    """
    kind = registration_kind or enrollment.registration_kind or StudentCourseUnitEnrollment.KIND_RETAKE
    if kind not in (
        StudentCourseUnitEnrollment.KIND_RETAKE,
        StudentCourseUnitEnrollment.KIND_MISSED,
    ):
        return None

    token = _idempotency_token(enrollment.id)
    existing = (
        StudentTuitionPayment.objects.filter(
            student=student,
            source="ad_hoc",
            notes__contains=token,
            is_waived=False,
        )
        .order_by("id")
        .first()
    )
    if existing:
        return existing

    amt, cur, head = resolve_retake_fee_amount(student)
    if amt <= 0:
        return None

    cu = enrollment.course_unit
    kind_label = "Missed paper" if kind == StudentCourseUnitEnrollment.KIND_MISSED else "Retake"
    label = f"{kind_label} · {cu.code}"[:200]
    notes = (
        f"Auto charge on {kind} registration. {token}. "
        f"Course: {cu.code} — {cu.name}."
    )[:2000]

    return StudentTuitionPayment.objects.create(
        student=student,
        source="ad_hoc",
        fee_head=head,
        label=label,
        amount=amt,
        currency=cur[:3],
        status="pending",
        notes=notes,
        charged_by=charged_by,
        semester=cu.semester if cu.semester_id else None,
    )
