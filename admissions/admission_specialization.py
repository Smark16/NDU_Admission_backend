"""Teaching subject combination helpers for admission and offer letters."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from admissions.models import AdmittedStudent


def admitted_subject_combination_label(admitted: AdmittedStudent) -> str:
    spec = getattr(admitted, "admitted_specialization", None)
    if spec is not None and getattr(spec, "name", None):
        return (spec.name or "").strip()
    return ""


def offer_letter_combination_context(admitted: AdmittedStudent) -> dict:
    combo = admitted_subject_combination_label(admitted)
    return {
        "subject_combination": combo,
        "specialization": combo,
        "teaching_subjects": combo,
    }


def validate_admitted_specialization_for_program(program, specialization) -> str | None:
    if program is None:
        return None
    if not getattr(program, "has_specialization", False):
        return None
    if specialization is None:
        return "Teaching subject combination is required for this programme."
    if specialization.program_id != program.id:
        return "Selected combination does not belong to the admitted programme."
    if not specialization.is_active:
        return "Selected teaching subject combination is not active."
    return None


def validate_offer_letter_admission(admitted: AdmittedStudent) -> str | None:
    program = getattr(admitted, "admitted_program", None)
    return validate_admitted_specialization_for_program(
        program,
        getattr(admitted, "admitted_specialization", None),
    )
