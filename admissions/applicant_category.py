"""Local vs international applicant classification (application fees, reporting, filters)."""
from __future__ import annotations

LOCAL_APPLICANT_COUNTRIES = frozenset({"Uganda", "Kenya", "Tanzania"})

APPLICANT_CATEGORY_LOCAL = "local"
APPLICANT_CATEGORY_INTERNATIONAL = "international"

APPLICANT_CATEGORY_CHOICES = (
    (APPLICANT_CATEGORY_LOCAL, "Local"),
    (APPLICANT_CATEGORY_INTERNATIONAL, "International"),
)


def is_local_nationality(nationality: str | None) -> bool:
    n = (nationality or "").strip().lower()
    if not n:
        return False
    if n in ("uganda", "kenya", "tanzania"):
        return True
    return n.startswith("tanzania") or "tanzania" in n


def category_from_nationality(nationality: str | None) -> str:
    if is_local_nationality(nationality):
        return APPLICANT_CATEGORY_LOCAL
    return APPLICANT_CATEGORY_INTERNATIONAL


def normalize_applicant_category(value: str | None) -> str:
    raw = (value or "").strip().lower()
    if raw in (APPLICANT_CATEGORY_LOCAL, "local"):
        return APPLICANT_CATEGORY_LOCAL
    if raw in (APPLICANT_CATEGORY_INTERNATIONAL, "international"):
        return APPLICANT_CATEGORY_INTERNATIONAL
    return ""


def category_label(category: str | None) -> str:
    if normalize_applicant_category(category) == APPLICANT_CATEGORY_LOCAL:
        return "Local"
    if normalize_applicant_category(category) == APPLICANT_CATEGORY_INTERNATIONAL:
        return "International"
    return ""
