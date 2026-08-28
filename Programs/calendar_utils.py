"""Programme calendar helpers (semester / trimester / modular)."""
from __future__ import annotations


def program_is_modular(program) -> bool:
    return (getattr(program, "calendar_type", None) or "") == "modular"


def max_terms_for_calendar(calendar_type: str | None) -> int:
    cal = (calendar_type or "semester").lower()
    if cal == "trimester":
        return 3
    if cal == "modular":
        return 12
    return 2


def period_unit_label(calendar_type: str | None, *, plural: bool = False) -> str:
    cal = (calendar_type or "semester").lower()
    if cal == "trimester":
        return "Trimesters" if plural else "Trimester"
    if cal == "modular":
        return "Sessions" if plural else "Session"
    return "Semesters" if plural else "Semester"


def calendar_type_display(calendar_type: str | None) -> str:
    cal = (calendar_type or "semester").lower()
    if cal == "trimester":
        return "Trimester (3 terms per year)"
    if cal == "modular":
        return "Modular (session / credit-based)"
    return "Semester (2 terms per year)"
