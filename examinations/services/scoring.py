"""Ndejje default: CA /40, exam contributes 60% of /100, sit if CA >= 17.5."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError


TWOPLACES = Decimal("0.01")


@dataclass(frozen=True)
class PolicyValues:
    ca_max: Decimal = Decimal("40")
    exam_weight: Decimal = Decimal("0.60")
    min_ca_to_sit_exam: Decimal = Decimal("17.5")
    pass_mark: Decimal = Decimal("50")


@dataclass
class ComputedResult:
    ca_mark: Decimal | None
    exam_mark: Decimal | None
    final_mark: Decimal | None
    exam_sitting_allowed: bool
    is_pass: bool | None
    grade_letter: str
    grade_point: Decimal | None


def _d(value) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value)).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def compute_course_result(
    *,
    ca_mark,
    exam_mark,
    policy: PolicyValues | None = None,
) -> ComputedResult:
    policy = policy or PolicyValues()
    ca = _d(ca_mark)
    exam = _d(exam_mark)

    if ca is not None and (ca < 0 or ca > policy.ca_max):
        raise ValidationError(f"CA must be between 0 and {policy.ca_max}.")

    if exam is not None and (exam < 0 or exam > 100):
        raise ValidationError("Exam mark must be between 0 and 100.")

    eligible = ca is not None and ca >= policy.min_ca_to_sit_exam

    if exam is not None and not eligible:
        raise ValidationError(
            f"Student cannot sit exam: CA must be at least {policy.min_ca_to_sit_exam} (of {policy.ca_max})."
        )

    final_mark = None
    is_pass = None
    if ca is not None and eligible and exam is not None:
        final_mark = (ca + exam * policy.exam_weight).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        is_pass = final_mark >= policy.pass_mark
    elif ca is not None and not eligible:
        final_mark = ca.quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    return ComputedResult(
        ca_mark=ca,
        exam_mark=exam if eligible else None,
        final_mark=final_mark,
        exam_sitting_allowed=eligible,
        is_pass=is_pass,
        grade_letter="",
        grade_point=None,
    )


def lookup_grade_band(final_mark: Decimal | None, bands) -> tuple[str, Decimal | None]:
    if final_mark is None:
        return "", None
    for band in bands:
        if band.min_mark <= final_mark <= band.max_mark:
            return band.letter, band.grade_point
    return "", None
