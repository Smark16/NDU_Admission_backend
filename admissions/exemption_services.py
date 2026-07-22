"""Exemption change-request helpers: form fee gate + eligible curriculum lines."""
from __future__ import annotations

import time
from decimal import Decimal

from django.conf import settings
from django.db import OperationalError, transaction
from django.utils import timezone

from admissions.models import AdmittedStudent, AdmissionChangeRequest
from payments.models import FeeHead, StudentTuitionPayment
from payments.student_payment_allocation import build_finance_allocation

EXEMPTION_FORM_FEE_CODE = "EXEMPTION_FORM"
EXEMPTION_COURSE_FEE_CODE = "EXEMPTION_COURSE"
EXEMPTION_FORM_FEE_UGX = Decimal(
    str(getattr(settings, "EXEMPTION_FORM_FEE_UGX", "50000"))
)


def ensure_exemption_fee_heads() -> tuple[FeeHead, FeeHead]:
    form_head, _ = FeeHead.objects.get_or_create(
        code=EXEMPTION_FORM_FEE_CODE,
        defaults={
            "name": "Exemption application form",
            "category": "service",
            "description": "One-time UGX fee to unlock the course exemption application form.",
            "is_active": True,
        },
    )
    course_head, _ = FeeHead.objects.get_or_create(
        code=EXEMPTION_COURSE_FEE_CODE,
        defaults={
            "name": "Course exemption fee",
            "category": "tuition",
            "description": "Per-course exemption fee billed by Accounts after Dean approval.",
            "is_active": True,
        },
    )
    return form_head, course_head


def _open_form_fee_charge(student: AdmittedStudent) -> StudentTuitionPayment | None:
    form_head, _ = ensure_exemption_fee_heads()
    return (
        StudentTuitionPayment.objects.filter(
            student=student,
            source="ad_hoc",
            fee_head=form_head,
            is_waived=False,
            status__in=("pending", "completed"),
        )
        .order_by("-created_at")
        .first()
    )


def form_fee_paid_for_charge(student: AdmittedStudent, charge: StudentTuitionPayment) -> bool:
    if charge.status == "completed":
        return True
    if charge.is_waived:
        return False
    alloc = build_finance_allocation(student)
    for line in alloc.demand_lines:
        if line.kind == "ad_hoc" and line.charge_id == charge.id:
            return line.status == "paid" or line.balance <= 0
    return False


def _ensure_form_fee_charge(student: AdmittedStudent, *, charged_by=None) -> StudentTuitionPayment:
    """Create the 50k form-fee charge if missing; retry on SQLite lock contention."""
    form_head, _ = ensure_exemption_fee_heads()
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            charge = _open_form_fee_charge(student)
            if charge is not None:
                return charge
            with transaction.atomic():
                charge = _open_form_fee_charge(student)
                if charge is not None:
                    return charge
                return StudentTuitionPayment.objects.create(
                    student=student,
                    source="ad_hoc",
                    fee_head=form_head,
                    label="Exemption application form fee",
                    amount=EXEMPTION_FORM_FEE_UGX,
                    currency="UGX",
                    status="pending",
                    notes="Auto-created to unlock course exemption change request form.",
                    charged_by=charged_by,
                    semester=None,
                )
        except OperationalError as exc:
            last_err = exc
            time.sleep(0.2 * (attempt + 1))
    if last_err:
        raise last_err
    raise OperationalError("Could not create exemption form fee charge.")


def ensure_exemption_form_fee_access(student: AdmittedStudent, *, charged_by=None) -> dict:
    """
    Ensure a 50k form-fee charge exists and report whether the form is unlocked.
    """
    charge = _ensure_form_fee_charge(student, charged_by=charged_by)

    paid = form_fee_paid_for_charge(student, charge)
    paid_at = None
    if paid:
        if charge.status != "completed":
            charge.status = "completed"
            if not charge.paid_at:
                charge.paid_at = timezone.now()
            charge.save(update_fields=["status", "paid_at", "updated_at"])
        paid_at = charge.paid_at

        AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
            form_fee_charge=charge,
            form_fee_paid_at__isnull=True,
        ).update(form_fee_paid_at=paid_at or timezone.now())

    balance = Decimal("0") if paid else Decimal(str(charge.amount))
    if not paid:
        alloc = build_finance_allocation(student)
        for line in alloc.demand_lines:
            if line.kind == "ad_hoc" and line.charge_id == charge.id:
                balance = line.balance
                break

    return {
        "paid": paid,
        "amount": float(EXEMPTION_FORM_FEE_UGX),
        "currency": "UGX",
        "balance": float(balance),
        "charge_id": charge.id,
        "charge_status": charge.status,
        "paid_at": paid_at.isoformat() if paid_at else None,
        "fee_head_code": EXEMPTION_FORM_FEE_CODE,
        "schoolpay_hint": (
            "Pay via SchoolPay using your student payment code. "
            "Refresh this page after payment posts."
        ),
    }


def student_is_exemption_form_unlocked(student: AdmittedStudent) -> bool:
    charge = _open_form_fee_charge(student)
    if charge is None:
        return False
    return form_fee_paid_for_charge(student, charge)


def list_eligible_exemption_courses(student: AdmittedStudent) -> list[dict]:
    """Curriculum lines for the student's pinned/default version, excluding existing exemptions."""
    from Programs.models import (
        ProgramCurriculumLine,
        StudentCurriculumOverride,
        resolve_program_default_curriculum_version,
    )

    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is None:
        return []

    version = enrollment.curriculum_version
    if version is None and enrollment.program_batch_id:
        version = enrollment.program_batch.curriculum_version
    if version is None:
        version = resolve_program_default_curriculum_version(enrollment.program)
    if version is None:
        return []

    existing = set(
        StudentCurriculumOverride.objects.filter(
            enrollment=enrollment,
            override_type__in=("exempted", "transferred"),
        ).values_list("curriculum_line_id", flat=True)
    )
    # Also exclude lines already on a pending exemption request
    pending_line_ids = set(
        AdmissionChangeRequest.objects.filter(
            admitted_student=student,
            change_type="exemption",
            status="pending",
        ).values_list("exemption_lines__curriculum_line_id", flat=True)
    )
    existing |= {i for i in pending_line_ids if i}

    lines = (
        ProgramCurriculumLine.objects.filter(
            curriculum_version=version,
            is_active=True,
            program_id=enrollment.program_id,
        )
        .select_related("catalog_course")
        .order_by("year_of_study", "term_number", "sort_order", "catalog_course__code")
    )
    out = []
    for line in lines:
        if line.id in existing:
            continue
        course = line.catalog_course
        out.append(
            {
                "id": line.id,
                "course_code": course.code if course else "",
                "course_name": course.name if course else "",
                "year_of_study": line.year_of_study,
                "term_number": line.term_number,
                "course_type": line.course_type,
            }
        )
    return out


def apply_exemption_overrides(change_request: AdmissionChangeRequest, decided_by) -> int:
    """Create exempted StudentCurriculumOverride rows. Returns count created."""
    from Programs.models import StudentCurriculumOverride

    if change_request.change_type != "exemption":
        return 0
    student = change_request.admitted_student
    try:
        enrollment = student.programme_enrollment
    except Exception:
        enrollment = None
    if enrollment is None:
        raise ValueError(
            "Student has no programme enrollment; cannot apply curriculum exemptions."
        )

    created = 0
    notes = (
        f"Approved via change request #{change_request.id}. "
        f"{(change_request.reason or '').strip()}"
    ).strip()
    for line in change_request.exemption_lines.select_related("curriculum_line"):
        if not line.curriculum_line_id:
            continue
        _, was_created = StudentCurriculumOverride.objects.get_or_create(
            enrollment=enrollment,
            curriculum_line_id=line.curriculum_line_id,
            defaults={
                "override_type": "exempted",
                "notes": notes[:2000],
                "decided_by": decided_by,
            },
        )
        if was_created:
            created += 1
        else:
            existing = StudentCurriculumOverride.objects.filter(
                enrollment=enrollment,
                curriculum_line_id=line.curriculum_line_id,
            ).first()
            if existing and existing.override_type != "exempted":
                existing.override_type = "exempted"
                existing.notes = notes[:2000]
                existing.decided_by = decided_by
                existing.save(
                    update_fields=["override_type", "notes", "decided_by", "updated_at"]
                )
                created += 1
    return created
