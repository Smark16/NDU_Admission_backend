"""Teaching subject combination helpers for admission and offer letters."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from admissions.models import AdmittedStudent


def program_requires_admission_specialization(program) -> bool:
    """True when admitted_specialization must be chosen at admission.

    Education programmes (e.g. teaching combinations) set the specialization entry
    point at year 1 term 1.  Other programmes (e.g. BBA tracks at year 3) choose
    later via enrollment — they must not block admission.
    """
    if program is None or not getattr(program, "has_specialization", False):
        return False
    from Programs.specialization_rules import (
        has_complete_specialization_entry,
        is_before_specialization_entry,
    )

    if not has_complete_specialization_entry(program):
        return False
    return not is_before_specialization_entry(program, 1, 1)


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
    if not program_requires_admission_specialization(program):
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
