"""
Test / exam registration eligibility.

Separate from course registration (registration_eligibility.py) and from
admin batch enrollment (admin_enrollment_requirements.py). Rule:
  - TEST: student must have paid >= 60% of current-term tuition.
  - EXAM: student must have paid 100% of current-term tuition.
  - Either kind: a student holding an active TemporaryAccessPass, or an
    active ScholarshipAward, may register regardless of the percentage paid.

A scholarship's own credit (once its waivers are applied) already raises
the tuition-paid percentage through the normal finance ledger, so this
check is a fallback for the gap between an award being created and its
credit actually being posted -- otherwise a scholarship student with a
still-unapplied award has no route to test/exam eligibility of their own,
and today only slips through if someone separately issued them a temp pass.

TemporaryAccessPass otherwise never grants registration (see
admissions/temporary_access.py) -- this is a narrow, test/exam-specific
exception, not a change to that policy. Course registration and admin
batch enrollment are untouched by this module.
"""
from __future__ import annotations

from admissions.models import AdmittedStudent

from .registration_eligibility import student_meets_min_tuition_pct

TEST_MIN_TUITION_PCT = 60.0
EXAM_MIN_TUITION_PCT = 100.0

KIND_TEST = "test"
KIND_EXAM = "exam"
KIND_THRESHOLDS = {
    KIND_TEST: TEST_MIN_TUITION_PCT,
    KIND_EXAM: EXAM_MIN_TUITION_PCT,
}


def student_has_temp_pass_bypass(student: AdmittedStudent) -> bool:
    from admissions.temporary_access import get_active_pass

    return get_active_pass(student) is not None


def student_has_active_scholarship_bypass(student: AdmittedStudent) -> bool:
    from .models import ScholarshipAward

    return ScholarshipAward.objects.filter(student=student, status="active").exists()


def test_exam_registration_block(student: AdmittedStudent, kind: str) -> str | None:
    """Return a block reason, or None if the student may register for this kind."""
    min_pct = KIND_THRESHOLDS.get(kind)
    if min_pct is None:
        raise ValueError(f"Unknown registration kind: {kind!r}")

    if student_has_temp_pass_bypass(student):
        return None

    if student_has_active_scholarship_bypass(student):
        return None

    if student_meets_min_tuition_pct(student, min_pct):
        return None

    label = "test" if kind == KIND_TEST else "exam"
    return (
        f"Student has not paid the minimum {min_pct:.0f}% of tuition required to "
        f"register for a {label}, and has no active temporary access pass or "
        f"active scholarship award."
    )


def student_eligible_for_test_exam(student: AdmittedStudent, kind: str) -> bool:
    return test_exam_registration_block(student, kind) is None
