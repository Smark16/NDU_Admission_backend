"""
Shared specialization rules for student academic flows.

Single production rule for:
- when a specialization choice is required to load courses (expected + registration)
- which specialization names are valid / shown as options
- early-save blocking (handled in enrollment_views select_specialization)
"""

from __future__ import annotations

from typing import Any

from django.db.models import Q

from .models import Program, ProgramCurriculumLine, ProgramSpecialization


MSG_EARLY_SPECIALIZATION = (
    "Specialization cannot be selected before the official specialization entry point."
)

MSG_PROGRAM_ENTRY_FIELDS = (
    "When a programme has specialization, both specialization_entry_year and "
    "specialization_entry_term must be set."
)

# AcademicLevel.name markers for programmes that do NOT use teaching-subject
# combinations (Education undergrad). Match carefully so "Undergraduate" is
# never treated as postgraduate via a bare "graduate" substring.
_POSTGRAD_LEVEL_EXACT = frozenset(
    {
        "postgraduate",
        "post-graduate",
        "post graduate",
        "masters",
        "master",
        "master's",
        "phd",
        "doctorate",
        "doctoral",
        "pgd",
        "pgde",
        "msc",
        "ma",
        "mba",
        "med",
        "meng",
    }
)
_POSTGRAD_LEVEL_SUBSTRINGS = (
    "postgraduate",
    "post-graduate",
    "post graduate",
    "masters",
    "master's",
    "doctorate",
    "doctoral",
    "pgde",
)


def normalize_specialization(value: Any) -> str:
    return (value or "").strip()


def is_postgraduate_program(program: Program | None) -> bool:
    """
    True for postgraduate / graduate award levels.

    Faculty of Education postgraduate programmes must not require teaching
    subject combinations (specialization) for registration.
    """
    if program is None:
        return False
    level = getattr(program, "academic_level", None)
    name = normalize_specialization(getattr(level, "name", None)).lower()
    if not name:
        return False
    if "undergrad" in name:
        return False
    if name in _POSTGRAD_LEVEL_EXACT:
        return True
    if any(s in name for s in _POSTGRAD_LEVEL_SUBSTRINGS):
        return True
    # Whole-word-ish PGD / PhD tokens
    tokens = {t.strip(".,()") for t in name.replace("/", " ").split()}
    if tokens & {"pgd", "pgde", "phd", "msc", "mba", "ma", "med", "meng"}:
        return True
    return False


def program_enforces_specialization_tracks(program: Program | None) -> bool:
    """has_specialization programmes excluding postgraduate award levels."""
    if program is None or not getattr(program, "has_specialization", False):
        return False
    if is_postgraduate_program(program):
        return False
    return True


def has_complete_specialization_entry(program: Program) -> bool:
    """If has_specialization is True, both entry year and term must be set."""
    if not program.has_specialization:
        return True
    return (
        program.specialization_entry_year is not None
        and program.specialization_entry_term is not None
    )


def is_before_specialization_entry(
    program: Program, year_of_study: int, term_number: int
) -> bool:
    """True if the student position is strictly before the configured entry point."""
    if not program.has_specialization:
        return False
    if not has_complete_specialization_entry(program):
        return False
    ey = int(program.specialization_entry_year)
    et = int(program.specialization_entry_term)
    if year_of_study < ey:
        return True
    if year_of_study == ey and term_number < et:
        return True
    return False


def _lines_for_term(
    program: Program,
    curriculum_version,
    year_of_study: int,
    term_number: int,
):
    from .curriculum_inheritance import curriculum_owner_program

    owner = curriculum_owner_program(program)
    qs = ProgramCurriculumLine.objects.filter(
        program=owner,
        year_of_study=year_of_study,
        term_number=term_number,
        is_active=True,
    )
    if curriculum_version is not None:
        qs = qs.filter(curriculum_version=curriculum_version)
    return qs


def distinct_tagged_specializations_for_term(
    program: Program,
    curriculum_version,
    year_of_study: int,
    term_number: int,
) -> list[str]:
    """Non-empty specialization values on curriculum lines for this term."""
    qs = (
        _lines_for_term(program, curriculum_version, year_of_study, term_number)
        .exclude(Q(specialization__isnull=True) | Q(specialization=""))
        .values_list("specialization", flat=True)
    )
    seen: set[str] = set()
    out: list[str] = []
    for raw in qs:
        spec = normalize_specialization(raw)
        if not spec:
            continue
        key = spec.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def authoritative_track_names(program: Program) -> list[str]:
    """ProgramSpecialization rows first; else distinct tags from all active lines."""
    explicit = list(
        ProgramSpecialization.objects.filter(program=program, is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if explicit:
        return explicit
    from .curriculum_inheritance import curriculum_owner_program

    owner = curriculum_owner_program(program)
    values = (
        ProgramCurriculumLine.objects.filter(program=owner, is_active=True)
        .exclude(Q(specialization__isnull=True) | Q(specialization=""))
        .values_list("specialization", flat=True)
    )
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        spec = normalize_specialization(raw)
        if not spec:
            continue
        key = spec.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(spec)
    return out


def allowed_specialization_names_for_validation(program: Program) -> list[str]:
    """Canonical list used to validate admin/student stored specialization."""
    return authoritative_track_names(program)


def resolve_specialization_for_program(
    program: Program, raw: Any
) -> tuple[str | None, str | None]:
    """
    Return (canonical_name, None) on success, (None, error_detail) if invalid.
    Empty raw returns (None, None).
    """
    requested = normalize_specialization(raw)
    if not requested:
        return None, None
    allowed = allowed_specialization_names_for_validation(program)
    if not allowed:
        return None, "This programme has no specialization tracks configured."
    matched = next((a for a in allowed if a.lower() == requested.lower()), None)
    if not matched:
        return None, f"'{requested}' is not a valid specialization for this programme."
    return matched, None


def compute_specialization_course_gate(
    program: Program,
    curriculum_version,
    year_of_study: int,
    term_number: int,
    selected_raw: Any,
) -> dict[str, Any]:
    """
    Unified gate for expected courses + registration available_courses.

    Returns keys:
      before_entry: bool
      requires_specialization: bool  # must choose a valid track to proceed
      available_specializations: list[str]  # for 400 payloads / GET specializations
      tagged_line_specializations: list[str]
    """
    selected = normalize_specialization(selected_raw)
    tagged = distinct_tagged_specializations_for_term(
        program, curriculum_version, year_of_study, term_number
    )
    explicit = list(
        ProgramSpecialization.objects.filter(program=program, is_active=True)
        .order_by("name")
        .values_list("name", flat=True)
    )
    # Options shown when at/past entry and this term needs a track-specific choice
    if explicit:
        option_list = explicit
    else:
        option_list = list(tagged)

    out: dict[str, Any] = {
        "before_entry": False,
        "requires_specialization": False,
        "available_specializations": [],
        "tagged_line_specializations": tagged,
    }

    if not program_enforces_specialization_tracks(program):
        return out

    if not has_complete_specialization_entry(program):
        # Misconfigured programme — do not hard-block students here; ProgramSerializer should prevent this.
        out["before_entry"] = True
        return out

    before = is_before_specialization_entry(program, year_of_study, term_number)
    out["before_entry"] = before
    if before:
        return out

    if not tagged:
        return out

    out["available_specializations"] = option_list
    allowed_lower = {c.lower() for c in option_list}
    missing = not selected
    invalid = bool(selected) and selected.lower() not in allowed_lower
    out["requires_specialization"] = missing or invalid
    return out
