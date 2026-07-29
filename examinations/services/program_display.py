"""Display helpers for examination / transcript documents."""
from __future__ import annotations

import re

# Campus / delivery site suffixes that should not appear on award lines.
_AWARD_CAMPUS_SUFFIX_RE = re.compile(
    r"""
    \s*
    (?:
        [-/\u2013\u2014]\s*Main(?:\s+Campus)?
      | \(\s*Main(?:\s+Campus)?\s*\)
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


def program_award_display_name(name: str | None) -> str:
    """
    Programme title for AWARD / transcript headers.

    Strips campus tags such as ``-Main`` / ``(Main)`` so documents show
    ``BACHELORS OF LAWS`` instead of ``BACHELORS OF LAWS-MAIN``.
    """
    if not name:
        return ""
    cleaned = str(name).strip()
    while True:
        next_cleaned = _AWARD_CAMPUS_SUFFIX_RE.sub("", cleaned).strip(" -/-\u2013\u2014")
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    return cleaned
