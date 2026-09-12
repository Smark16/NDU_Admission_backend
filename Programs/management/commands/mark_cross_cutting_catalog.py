"""
Mark common Sem I cross-cutting catalog papers.

Dry-run by default; pass --apply to write.

Examples:
  python manage.py mark_cross_cutting_catalog
  python manage.py mark_cross_cutting_catalog --apply
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db.models import Q

from Programs.models import CourseCatalogUnit

DEFAULT_NOTE = (
    "Often shared across programmes/faculties; use Shared Teaching when same sitting. "
    "Engineering parallel streams stay programme-only (Teaching Sections)."
)

# Exact codes (normalized: upper, spaces stripped for match)
EXACT_CODES = {
    "CEV1101",
    "CIT1103",
    "ENG1101",  # Engineering Communication Skills (when shared sitting)
}

# Substring match on normalized code (no spaces)
CODE_SUBSTRINGS = (
    "CISCO",
    "HAUWEI",
    "HUAWEI",
)

# Title keywords (case-insensitive) — only if not already exact-matched
TITLE_KEYWORDS = (
    "christian ethics",
    "communication skills",
    "computer literacy",
    "entrepreneurship",
    "cisco practical",
    "introduction to information technology",
)


def _norm_code(code: str) -> str:
    return re.sub(r"\s+", "", (code or "").upper())


def _matches(unit: CourseCatalogUnit) -> bool:
    norm = _norm_code(unit.code)
    if norm in EXACT_CODES or any(norm == c for c in EXACT_CODES):
        return True
    # Also match codes that end with the same digits as exact list when prefix varies
    for exact in EXACT_CODES:
        if norm.endswith(exact) or exact.endswith(norm):
            if len(norm) >= 6 and (norm[-7:] == exact or norm == exact):
                return True
    if any(s in norm for s in CODE_SUBSTRINGS):
        return True
    # Common Ndejje ethics / literacy style codes across faculties
    if re.search(r"(CEV|ETH)\d{3,4}$", norm) or re.search(r"1101$", norm) and "ETHIC" in (
        unit.title or ""
    ).upper().replace(" ", ""):
        title_u = (unit.title or "").upper()
        if "ETHIC" in title_u:
            return True
    title = (unit.title or "").lower()
    return any(k in title for k in TITLE_KEYWORDS)


class Command(BaseCommand):
    help = "Mark catalog papers that commonly cross-cut programmes (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write is_cross_cutting=True (default is dry-run).",
        )
        parser.add_argument(
            "--note",
            default=DEFAULT_NOTE,
            help="Note stored on newly marked rows (default explains Shared Teaching).",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        note = (options.get("note") or DEFAULT_NOTE).strip()[:255]

        qs = CourseCatalogUnit.objects.filter(is_active=True).order_by("code")
        to_mark = [u for u in qs if _matches(u)]
        already = [u for u in to_mark if u.is_cross_cutting]
        pending = [u for u in to_mark if not u.is_cross_cutting]

        self.stdout.write(
            f"Matched {len(to_mark)} catalog unit(s) "
            f"({len(already)} already marked, {len(pending)} pending)."
        )
        for u in to_mark:
            flag = "KEEP" if u.is_cross_cutting else ("APPLY" if apply else "WOULD")
            self.stdout.write(f"  [{flag}] {u.code} — {u.title}")

        if not apply:
            self.stdout.write(self.style.WARNING("Dry-run only. Re-run with --apply to save."))
            return

        updated = 0
        for u in pending:
            u.is_cross_cutting = True
            if not (u.cross_cutting_note or "").strip():
                u.cross_cutting_note = note
            u.save(update_fields=["is_cross_cutting", "cross_cutting_note", "updated_at"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Marked {updated} catalog unit(s) as cross-cutting."))
