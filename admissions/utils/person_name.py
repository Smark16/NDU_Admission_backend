"""Normalize person name parts for display and matching."""
from __future__ import annotations

import re


def normalize_name_part(value: str | None) -> str:
    """Strip and collapse internal whitespace in one name field."""
    return re.sub(r"\s+", " ", str(value or "").strip())


def format_person_name(*parts: str | None) -> str:
    """Join non-empty name parts with a single space (no double gaps when middle is blank)."""
    cleaned = [normalize_name_part(p) for p in parts]
    return " ".join(p for p in cleaned if p)
