"""Validate that course results have required marks before verify/publish."""
from __future__ import annotations

from decimal import Decimal

from ..models import AssessmentPolicy, CourseUnitResult


def _d(value) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def result_completeness_error(
    result: CourseUnitResult,
    *,
    policy: AssessmentPolicy | None = None,
) -> str | None:
    """Return an error message when marks are incomplete, else None."""
    policy = policy or result.policy
    if result.ca_mark is None:
        return "CA mark is required."

    ca = _d(result.ca_mark)
    if ca is None:
        return "CA mark is required."

    min_ca = policy.min_ca_to_sit_exam
    if ca >= min_ca and result.exam_mark is None:
        return f"Exam mark is required (CA ≥ {min_ca})."

    return None


def collect_incomplete_results(results) -> list[dict]:
    """List {reg_no, enrollment_id, detail} for results missing required marks."""
    incomplete = []
    for result in results.select_related("enrollment__student"):
        err = result_completeness_error(result)
        if err:
            student = result.enrollment.student
            incomplete.append(
                {
                    "reg_no": student.reg_no or "",
                    "enrollment_id": result.enrollment_id,
                    "detail": err,
                }
            )
    return incomplete
