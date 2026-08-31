"""Keep registration numbers aligned with campus / programme / study mode.

SchoolPay payment codes must never be rewritten when placement changes —
ledger history is tied to the existing code.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError

logger = logging.getLogger(__name__)

PROGRAMME_CHANGE_FEE_CODE = "PROGRAMME_CHANGE"
PROGRAMME_CHANGE_FEE_UGX = Decimal("80000")


def _intake_batch_for_reg(admission):
    """Prefer the admission intake batch used for original numbering."""
    return getattr(admission, "admitted_batch", None)


def regenerate_reg_no_for_admission(admission, *, sync_portal: bool = True) -> str | None:
    """
    Assign a new reg_no from current campus, programme, and study mode.
    Does not modify schoolpay_code / is_registered_with_schoolpay.
    Returns the new reg_no (or None if generation was skipped).
    """
    from admissions.utils.reg_no import generate_reg_no

    campus = admission.admitted_campus
    program = admission.admitted_program
    study_mode = (admission.study_mode or "").strip()
    if campus is None or program is None or not study_mode:
        logger.warning(
            "reg_no regen skipped for admission %s (campus/program/study_mode incomplete)",
            admission.pk,
        )
        return None

    new_reg = generate_reg_no(
        campus=campus,
        program=program,
        study_mode=study_mode,
        batch=_intake_batch_for_reg(admission),
        exclude_admission_id=admission.pk,
    )
    old_reg = (admission.reg_no or "").strip()
    if new_reg == old_reg:
        return old_reg or None

    admission.reg_no = new_reg
    for attempt in range(5):
        try:
            admission.save(update_fields=["reg_no", "updated_at"])
            break
        except IntegrityError:
            if attempt >= 4:
                raise
            from admissions.utils.reg_no import generate_reg_no

            new_reg = generate_reg_no(
                campus=campus,
                program=program,
                study_mode=study_mode,
                batch=_intake_batch_for_reg(admission),
                exclude_admission_id=admission.pk,
            )
            admission.reg_no = new_reg

    if sync_portal:
        try:
            from admissions.student_accounts import ensure_student_portal_account

            ensure_student_portal_account(admission)
        except Exception:
            logger.exception(
                "Portal username sync failed after reg_no change for admission %s",
                admission.pk,
            )

    logger.info(
        "Regenerated reg_no for admission %s: %s → %s (SchoolPay unchanged: %s)",
        admission.pk,
        old_reg,
        new_reg,
        admission.schoolpay_code or "—",
    )
    return new_reg


def bill_programme_change_if_required(
    admission,
    *,
    old_program=None,
    new_program=None,
    charged_by=None,
):
    """
    Raise the post-document-verification programme-change charge.

    This only applies when the admitted programme actually changes after the
    student's physical documents have already been verified.
    """
    old_program_id = getattr(old_program, "id", old_program)
    new_program_id = getattr(new_program, "id", new_program)
    if not old_program_id or not new_program_id or old_program_id == new_program_id:
        return None
    if not getattr(admission, "physical_documents_verified", False):
        return None

    from payments.models import FeeHead, StudentTuitionPayment

    fee_head, _ = FeeHead.objects.get_or_create(
        code=PROGRAMME_CHANGE_FEE_CODE,
        defaults={
            "name": "Programme Change Fee",
            "category": "service",
            "description": "Administrative charge for programme/course changes after physical document verification.",
            "is_active": True,
        },
    )
    marker = f"programme_change:{admission.pk}:{old_program_id}->{new_program_id}"
    existing = StudentTuitionPayment.objects.filter(
        student=admission,
        source="ad_hoc",
        fee_head=fee_head,
        is_waived=False,
        notes__icontains=marker,
    ).exclude(status="cancelled").first()
    if existing is not None:
        return existing

    old_name = getattr(old_program, "name", None) or f"Programme #{old_program_id}"
    new_name = getattr(new_program, "name", None) or f"Programme #{new_program_id}"
    return StudentTuitionPayment.objects.create(
        student=admission,
        source="ad_hoc",
        fee_head=fee_head,
        label="Programme change fee",
        amount=PROGRAMME_CHANGE_FEE_UGX,
        currency="UGX",
        status="pending",
        notes=(
            f"{marker}; Charged after physical document verification for programme change "
            f"from {old_name} to {new_name}."
        ),
        charged_by=charged_by,
        semester=None,
    )


def _course_units_for_program_q(program_id: int):
    from django.db.models import Q

    return Q(course_unit__program_batch__program_id=program_id) | Q(
        course_unit__semester__program_batch__program_id=program_id
    )


def reset_academic_registration_for_programme_change(
    admission,
    *,
    old_program_id: int | None,
    new_program_id: int | None,
) -> dict:
    """
    On programme change: withdraw old-programme course rows, clear official
    registration, reset SPE to Y1T1, drop stale curriculum overrides, and
    auto-assign the new programme's current-term courses.
    """
    from django.utils import timezone

    from Programs.models import (
        StudentCourseUnitEnrollment,
        StudentCurriculumOverride,
        StudentProgrammeEnrollment,
    )
    from payments.programme_enrollment_activation import (
        _auto_assign_current_semester_course_units,
    )

    if not old_program_id or not new_program_id or old_program_id == new_program_id:
        return {"reset": False, "reason": "no_program_change"}

    now = timezone.now()
    withdrawn_old = StudentCourseUnitEnrollment.objects.filter(
        student=admission,
        status="enrolled",
    ).filter(_course_units_for_program_q(old_program_id)).update(
        status="withdrawn",
        registration_date=None,
        updated_at=now,
    )

    withdrawn_other = (
        StudentCourseUnitEnrollment.objects.filter(
            student=admission,
            status="enrolled",
        )
        .exclude(_course_units_for_program_q(new_program_id))
        .update(
            status="withdrawn",
            registration_date=None,
            updated_at=now,
        )
    )

    student_updates: list[str] = []
    if admission.is_registered:
        admission.is_registered = False
        student_updates.append("is_registered")
    if admission.registration_date is not None:
        admission.registration_date = None
        student_updates.append("registration_date")
    if student_updates:
        student_updates.append("updated_at")
        admission.save(update_fields=student_updates)

    try:
        spe = StudentProgrammeEnrollment.objects.get(student=admission)
    except StudentProgrammeEnrollment.DoesNotExist:
        return {
            "reset": True,
            "withdrawn_old_program_courses": withdrawn_old,
            "withdrawn_other_courses": withdrawn_other,
            "spe_reset": False,
            "reason": "no_spe",
        }

    overrides_deleted, _ = StudentCurriculumOverride.objects.filter(
        enrollment=spe
    ).delete()

    spe.current_year_of_study = 1
    spe.current_term_number = 1
    spe.save(
        update_fields=["current_year_of_study", "current_term_number", "updated_at"]
    )

    auto = _auto_assign_current_semester_course_units(spe)
    return {
        "reset": True,
        "withdrawn_old_program_courses": withdrawn_old,
        "withdrawn_other_courses": withdrawn_other,
        "curriculum_overrides_deleted": overrides_deleted,
        "spe_reset": True,
        **auto,
    }


def apply_program_campus_study_mode(
    admission,
    *,
    program=None,
    campus=None,
    study_mode: str | None = None,
    regenerate_reg_no: bool = True,
    charged_by=None,
):
    """
    Apply placement updates and regenerate the campus/programme-sensitive reg_no.
    Never changes schoolpay_code.
    """
    placement_changed = False
    update_fields: list[str] = []
    old_program = admission.admitted_program
    program_changed = False

    if program is not None and admission.admitted_program_id != getattr(program, "id", program):
        admission.admitted_program = program
        update_fields.append("admitted_program")
        placement_changed = True
        program_changed = True

    if campus is not None and admission.admitted_campus_id != getattr(campus, "id", campus):
        admission.admitted_campus = campus
        update_fields.append("admitted_campus")
        placement_changed = True

    if study_mode is not None:
        mode = str(study_mode).strip()
        if mode and mode != (admission.study_mode or ""):
            admission.study_mode = mode
            update_fields.append("study_mode")
            placement_changed = True

    if update_fields:
        update_fields.append("updated_at")
        admission.save(update_fields=update_fields)
        if program_changed:
            from admissions.serializers import AdmittedStudentSerializer

            old_program_id = getattr(old_program, "id", old_program)
            AdmittedStudentSerializer._sync_programme_enrollment_batch(admission)
            reset_academic_registration_for_programme_change(
                admission,
                old_program_id=old_program_id,
                new_program_id=admission.admitted_program_id,
            )
            bill_programme_change_if_required(
                admission,
                old_program=old_program,
                new_program=admission.admitted_program,
                charged_by=charged_by,
            )

    new_reg = None
    if regenerate_reg_no and placement_changed:
        new_reg = regenerate_reg_no_for_admission(admission, sync_portal=True)

    return {
        "admission": admission,
        "placement_changed": placement_changed,
        "reg_no": admission.reg_no,
        "previous_reg_no_replaced": bool(new_reg),
        "schoolpay_code": admission.schoolpay_code,
    }
