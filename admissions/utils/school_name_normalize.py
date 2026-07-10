"""
Normalize secondary / A-Level school names for analytics grouping.

Applicants often type the same school differently, e.g. "Mengo ss", "MENGO SS",
"Mengo", "mengo s.s." — these should count as one school in charts and exports.
"""
from __future__ import annotations

import re

from django.db.models import Count, F, Max
from django.db.models.functions import Lower, Trim

_INVALID_SCHOOL_TOKENS = frozenset(
    {"", "n/a", "na", "none", "-", "--", "null", "nil", "tbd", "pending", "n.a.", "n.a"}
)

_INDEX_KEY_PREFIX = "__index__:"

# Trailing suffixes stripped for grouping (applied repeatedly, case-insensitive).
_SCHOOL_SUFFIX_PATTERNS = (
    re.compile(r"\s+s\.?\s*s\.?\s*$", re.IGNORECASE),  # ss, s.s., s s
    re.compile(r"\s+secondary\s+school\s*$", re.IGNORECASE),
    re.compile(r"\s+sec\.?\s+school\s*$", re.IGNORECASE),
    re.compile(r"\s+sec\.?\s+sch(?:ool)?\s*$", re.IGNORECASE),
    re.compile(r"\s+high\s+school\s*$", re.IGNORECASE),
)


def looks_like_centre_or_index_only(text: str) -> bool:
    """True when the value has no letters (digits/punctuation only)."""
    t = (text or "").strip()
    if not t:
        return True
    return not any(ch.isalpha() for ch in t)


def normalize_school_group_key(text: str) -> str:
    """Canonical lowercase key for merging school name variants."""
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[_\-./\\]+", " ", t)
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if not t or t in _INVALID_SCHOOL_TOKENS:
        return ""
    changed = True
    while changed:
        changed = False
        for pat in _SCHOOL_SUFFIX_PATTERNS:
            new_t = pat.sub("", t).strip()
            if new_t != t:
                t = new_t
                changed = True
    return t


def school_bucket_key(school: str, index: str = "") -> str:
    """Bucket key for one application row (school name preferred, else index)."""
    st = (school or "").strip()
    ix = (index or "").strip()
    ix_l = ix.lower()

    if st and not looks_like_centre_or_index_only(st):
        key = normalize_school_group_key(st)
        if key and key not in _INVALID_SCHOOL_TOKENS:
            return key

    if ix and ix_l not in _INVALID_SCHOOL_TOKENS:
        return f"{_INDEX_KEY_PREFIX}{ix_l}"

    if st:
        key = normalize_school_group_key(st)
        if key and key not in _INVALID_SCHOOL_TOKENS:
            return key
    return ""


def school_display_rank(name: str) -> int:
    """Prefer richer spellings when picking a chart label from a bucket."""
    if not name:
        return 0
    n = name.strip()
    score = len(n)
    if re.search(r"\bss\b", n, re.IGNORECASE):
        score += 20
    if re.search(r"school", n, re.IGNORECASE):
        score += 10
    if n != n.lower() and n != n.upper():
        score += 5
    return score


def format_school_display(name: str) -> str:
    """Readable title-style label (keeps SS uppercase)."""
    if not name:
        return ""
    parts = re.split(r"\s+", name.strip())
    out: list[str] = []
    for part in parts:
        bare = part.rstrip(".")
        low = bare.lower()
        if low in {"ss", "s", "s.s"}:
            out.append("SS")
        else:
            out.append(bare.capitalize())
    return " ".join(out)


def display_top_school_label(group_key: str, sample_school: str, sample_index: str) -> str:
    """Chart/CSV label for a normalized school bucket."""
    if group_key.startswith(_INDEX_KEY_PREFIX):
        ix = sample_index.strip() or group_key[len(_INDEX_KEY_PREFIX) :]
        return f"A-Level centre / index: {ix}"

    ss = (sample_school or "").strip()
    ix = (sample_index or "").strip()
    ix_l = ix.lower()
    if ix_l in _INVALID_SCHOOL_TOKENS:
        ix = ""
    if ss and not looks_like_centre_or_index_only(ss):
        return format_school_display(ss)
    if ix:
        return f"A-Level centre / index: {ix}"
    if ss:
        return format_school_display(ss)
    return format_school_display(group_key) or group_key or "Unknown"


def aggregate_top_schools(qs, *, limit: int = 10) -> list[dict]:
    """
    Top schools by application count, merging case/spacing/SS suffix variants.

    qs: Application queryset (already filtered).
    """
    rows = (
        qs.annotate(_st=Trim("alevel_school"), _ix=Trim("alevel_index_number"))
        .annotate(_st_l=Lower(F("_st")), _ix_l=Lower(F("_ix")))
        .values("_st_l", "_ix_l")
        .annotate(
            count=Count("id"),
            sample_school=Max("_st"),
            sample_index=Max("_ix"),
        )
    )

    buckets: dict[str, dict] = {}

    for row in rows:
        st = (row.get("sample_school") or "").strip()
        ix = (row.get("sample_index") or "").strip()
        count = int(row["count"] or 0)
        if count <= 0:
            continue

        key = school_bucket_key(st, ix)
        if not key:
            continue

        if key not in buckets:
            buckets[key] = {"count": 0, "sample_school": st, "sample_index": ix}
        buckets[key]["count"] += count
        if school_display_rank(st) > school_display_rank(buckets[key]["sample_school"]):
            buckets[key]["sample_school"] = st
            buckets[key]["sample_index"] = ix

    ranked = sorted(buckets.items(), key=lambda item: -item[1]["count"])[:limit]
    return [
        {
            "school_name": display_top_school_label(key, data["sample_school"], data["sample_index"]),
            "count": data["count"],
            "group_key": key,
        }
        for key, data in ranked
    ]
