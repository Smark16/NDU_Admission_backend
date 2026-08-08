"""Helpers for hostel assignment UX (natural room codes, floor bands)."""
from __future__ import annotations

import re

from admissions.registration_workflow import student_curriculum_year_term

from .eligibility import is_first_year_first_term, student_gender
from .models import Building, Floor, Hostel


def natural_room_sort_key(code: str) -> tuple:
    """
    Sort room codes so NAR09 comes before NAR11.
    Groups by non-numeric prefix, then trailing integer.
    """
    text = (code or "").strip()
    match = re.search(r"(\d+)\s*$", text)
    if not match:
        return (text.upper(), 0, text.upper())
    prefix = text[: match.start()].upper()
    return (prefix, int(match.group(1)), text.upper())


def student_cohort_type(student) -> str:
    """fresher (Y1T1) vs continuing — drives suggested floor band."""
    if is_first_year_first_term(student):
        return "fresher"
    year, _term = student_curriculum_year_term(student)
    if year == 1:
        return "fresher"
    return "continuing"


def building_floor_sort_orders(building: Building) -> list[int]:
    """Distinct floor sort_order values for a hall, low → high."""
    return sorted(
        {
            int(o)
            for o in Floor.objects.filter(building=building).values_list(
                "sort_order", flat=True
            )
            if o is not None
        }
    )


def suggested_floor_sort_orders(
    building: Building, *, band: str, hostel: Hostel | None = None
) -> list[int]:
    """
    Soft floor guidance relative to THIS building's levels.

    - fresher / upper: the highest N floors in this hall
    - continuing / lower: the lowest N floors in this hall
    - single-level halls: that one floor is always suggested

    N comes from hostel.fresher_min_sort_order / continuing_max_sort_order
    (counts from the extreme, not absolute sort_order thresholds).
    """
    orders = building_floor_sort_orders(building)
    if not orders:
        return []
    if len(orders) == 1 or band in ("", "all", None):
        return orders

    h = hostel or building.hostel
    if band == "fresher":
        n = max(1, int(getattr(h, "fresher_min_sort_order", None) or 1))
        return orders[-min(n, len(orders)) :]
    if band == "continuing":
        n = max(1, int(getattr(h, "continuing_max_sort_order", None) or 1))
        return orders[: min(n, len(orders))]
    return orders


def floor_matches_band(floor, *, band: str, hostel: Hostel) -> bool:
    """band: 'fresher' | 'continuing' | 'all' — building-relative."""
    if band in ("", "all", None):
        return True
    building = getattr(floor, "building", None)
    if building is None:
        return True
    allowed = set(suggested_floor_sort_orders(building, band=band, hostel=hostel))
    return int(getattr(floor, "sort_order", 0) or 0) in allowed


def enrichment_for_student(student) -> dict:
    gender = student_gender(student)
    year, term = student_curriculum_year_term(student)
    cohort = student_cohort_type(student)
    app = getattr(student, "application", None)
    phone = (getattr(app, "phone", None) or "").strip() or None
    kin_name = (getattr(app, "next_of_kin_name", None) or "").strip() or None
    kin_contact = (getattr(app, "next_of_kin_contact", None) or "").strip() or None
    kin_rel = (getattr(app, "next_of_kin_relationship", None) or "").strip() or None
    return {
        "gender": gender,
        "cohort": cohort,
        "is_fresher": cohort == "fresher",
        "year_of_study": year,
        "term_number": term,
        "year_term_label": f"Y{year}T{term}",
        "phone": phone,
        "next_of_kin_name": kin_name,
        "next_of_kin_contact": kin_contact,
        "next_of_kin_relationship": kin_rel,
    }
