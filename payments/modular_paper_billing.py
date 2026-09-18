"""
Per-paper tuition billing for modular (Graduate School) programmes.

A modular session's tuition is divided evenly across the session's papers
(Program.modular_papers_per_session, default 6). Functional fees are billed
separately, 100% upfront per session, via the existing FUNCTIONAL_FEE flow —
this module only handles the tuition slice, and only fires for course units
belonging to a program_is_modular() programme.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from admissions.models import AdmittedStudent
from Programs.models import CourseUnit

from .models import FeeHead, StudentTuitionPayment

MODULAR_PAPER_FEE_CODE = "MODULAR_PAPER_FEE"
DEFAULT_PAPERS_PER_SESSION = 6


def get_or_create_modular_paper_fee_head() -> FeeHead:
    head, _ = FeeHead.objects.get_or_create(
        code=MODULAR_PAPER_FEE_CODE,
        defaults={
            "name": "Modular paper tuition",
            "category": "tuition",
            "description": (
                "Per-paper tuition slice for modular (Graduate School) programmes: "
                "session tuition divided across the session's papers, billed once "
                "per registered paper."
            ),
            "is_active": True,
        },
    )
    return head


def papers_per_session_for_program(program) -> int:
    n = getattr(program, "modular_papers_per_session", None) if program else None
    return int(n) if n else DEFAULT_PAPERS_PER_SESSION


def per_paper_tuition_amount(student: AdmittedStudent, cu: CourseUnit) -> Decimal | None:
    """Session tuition ÷ papers_per_session for this course unit's semester. None if unconfigured."""
    from admissions.exemption_services import semester_tuition_amount_for_student

    sem = cu.semester
    if sem is None or sem.year_of_study is None or sem.term_number is None:
        return None
    tuition = semester_tuition_amount_for_student(
        student, year_of_study=sem.year_of_study, term_number=sem.term_number
    )
    if tuition is None:
        return None
    program = cu.program_batch.program if cu.program_batch_id else None
    papers = papers_per_session_for_program(program)
    return (tuition / Decimal(papers)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _idempotency_token(student_id: int, course_unit_id: int) -> str:
    return f"modular_paper student_id={student_id} course_unit_id={course_unit_id}"


def existing_paper_charge(
    student: AdmittedStudent, cu: CourseUnit
) -> StudentTuitionPayment | None:
    token = _idempotency_token(student.id, cu.id)
    return (
        StudentTuitionPayment.objects.filter(
            student=student,
            source="ad_hoc",
            notes__contains=token,
        )
        .order_by("id")
        .first()
    )


def ensure_paper_charge(
    student: AdmittedStudent, cu: CourseUnit, *, charged_by=None
) -> StudentTuitionPayment | None:
    """Idempotently create the pending per-paper charge. None if tuition isn't configured."""
    existing = existing_paper_charge(student, cu)
    if existing:
        return existing
    amount = per_paper_tuition_amount(student, cu)
    if amount is None or amount <= 0:
        return None
    head = get_or_create_modular_paper_fee_head()
    token = _idempotency_token(student.id, cu.id)
    return StudentTuitionPayment.objects.create(
        student=student,
        source="ad_hoc",
        fee_head=head,
        label=f"Paper tuition · {cu.code}"[:200],
        amount=amount,
        currency="UGX",
        status="pending",
        notes=(
            f"Auto charge on modular paper registration. {token}. "
            f"Course: {cu.code} — {cu.name}."
        )[:2000],
        charged_by=charged_by,
        semester=cu.semester,
    )


def paper_charge_paid(charge: StudentTuitionPayment | None) -> bool:
    if charge is None:
        return False
    if charge.is_waived:
        return True
    if charge.status == "completed":
        return True
    if charge.status == "pending" and (charge.payment_reference or "").strip():
        try:
            from payments.utils.tuition_payment_status import (
                reconcile_pending_tuition_payment,
            )

            reconcile_pending_tuition_payment(charge)
            charge.refresh_from_db()
        except Exception:
            pass
        return charge.status == "completed"
    return False


def modular_paper_registration_gate(
    student: AdmittedStudent, cu: CourseUnit, *, charged_by=None
) -> tuple[bool, str]:
    """
    Hard gate: True only once this paper's tuition slice is paid.
    Creates the pending charge (if missing) so it shows up for the student to pay.
    """
    amount = per_paper_tuition_amount(student, cu)
    if amount is None:
        return False, (
            f"Tuition is not configured for {cu.code}'s session — Accounts must set "
            "it up before this paper can be registered."
        )
    charge = ensure_paper_charge(student, cu, charged_by=charged_by)
    if charge is None:
        return False, f"Could not determine the per-paper fee for {cu.code}."
    if paper_charge_paid(charge):
        return True, ""
    return False, (
        f"Pay {charge.currency} {float(charge.amount):,.0f} for {cu.code} before "
        "registering for this paper."
    )
