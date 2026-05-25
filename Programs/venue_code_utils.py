"""Auto-generate classroom codes and maintain room type labels."""
from __future__ import annotations

import re

from Programs.models import RoomType, Venue

DEFAULT_ROOM_TYPES = (
    "Lecture room",
    "Laboratory",
    "Hall / auditorium",
    "Office / seminar",
    "Other",
)


def slug_part(text: str, *, max_len: int = 16) -> str:
    """Uppercase alphanumeric chunks joined by hyphens."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # "Block D" -> keep D; "D21" -> D21
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").upper()
    return cleaned[:max_len]


def suggest_venue_code(*, campus_code: str, campus_name: str, building: str, name: str) -> str:
    """
    Build a short code from campus + block/building + room name.

    Examples:
      Main / Block D / D21  -> MAIN-D-D21
      Luwero / Block A / A12 -> LUW-A-A12
    """
    campus_bit = slug_part(campus_code, max_len=8) or slug_part(campus_name, max_len=8) or "NDU"
    building_bit = slug_part(building, max_len=10)
    if building_bit.startswith("BLOCK-"):
        building_bit = building_bit.replace("BLOCK-", "", 1)
    name_bit = slug_part(name, max_len=14)
    parts = [p for p in (campus_bit, building_bit, name_bit) if p]
    return "-".join(parts)[:40]


def unique_venue_code_for_campus(campus_id: int, base: str, *, exclude_venue_id: int | None = None) -> str:
    """Return *base* or base-2, base-3 if taken on this campus."""
    code = (base or "").strip().upper()
    if not code:
        return ""
    qs = Venue.objects.filter(campus_id=campus_id, code__iexact=code)
    if exclude_venue_id:
        qs = qs.exclude(pk=exclude_venue_id)
    if not qs.exists():
        return code
    for n in range(2, 100):
        candidate = f"{code}-{n}"[:40]
        if not Venue.objects.filter(campus_id=campus_id, code__iexact=candidate).exclude(
            pk=exclude_venue_id or 0
        ).exists():
            return candidate
    return f"{code[:36]}-X"


def ensure_room_type(name: str) -> str:
    """Normalize label and ensure it exists in the room type registry."""
    label = " ".join((name or "").split()).strip()
    if not label:
        label = "Other"
    if len(label) > 40:
        label = label[:40]
    RoomType.objects.get_or_create(name=label, defaults={"is_active": True})
    return label


def list_room_type_names() -> list[str]:
    from_db = list(
        RoomType.objects.filter(is_active=True).order_by("name").values_list("name", flat=True)
    )
    seen = set()
    out = []
    for name in list(DEFAULT_ROOM_TYPES) + from_db:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out
