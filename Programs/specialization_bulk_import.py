"""Bulk import teaching subject combinations / programme specializations from CSV."""
from __future__ import annotations

import csv
import io
from typing import Any

from Programs.models import Program, ProgramSpecialization

REQUIRED_COLUMN = "name"
OPTIONAL_COLUMNS = ("is_active",)

TEMPLATE_ROWS = [
    {"name": "Mathematics & Physics", "is_active": "true"},
    {"name": "Mathematics & Biology", "is_active": "true"},
    {"name": "Mathematics & Chemistry", "is_active": "true"},
]


def build_specialization_import_template_csv() -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[REQUIRED_COLUMN, *OPTIONAL_COLUMNS])
    writer.writeheader()
    writer.writerows(TEMPLATE_ROWS)
    return output.getvalue()


def _norm_col(name: str) -> str:
    return (name or "").strip().lower().replace(" ", "_")


def _as_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "t"):
        return True
    if text in ("0", "false", "no", "n", "f"):
        return False
    return None


def _resolve_columns(fieldnames: list[str] | None) -> dict[str, str]:
    col_map = {
        "name": "name",
        "specialization": "name",
        "specialization_name": "name",
        "combination": "name",
        "subject_combination": "name",
        "teaching_subject_combination": "name",
        "teaching_subjects": "name",
        "is_active": "is_active",
        "active": "is_active",
    }
    resolved: dict[str, str] = {}
    for raw_col in fieldnames or []:
        key = col_map.get(_norm_col(raw_col))
        if key and key not in resolved:
            resolved[key] = raw_col
    return resolved


def process_specialization_bulk_import(program: Program, file_text: str) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(file_text))
    if not reader.fieldnames:
        return {"ok": False, "detail": "CSV file is empty or has no header row."}

    resolved = _resolve_columns(reader.fieldnames)
    if "name" not in resolved:
        return {
            "ok": False,
            "detail": 'CSV must include a "name" column (one combination per row).',
        }

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []
    seen_in_file: set[str] = set()

    for row_num, raw in enumerate(reader, start=2):
        row = {key: (raw.get(raw_col) or "").strip() for key, raw_col in resolved.items()}
        name = (row.get("name") or "").strip()
        if not name:
            skipped += 1
            continue

        key = name.casefold()
        if key in seen_in_file:
            errors.append(
                {
                    "row": row_num,
                    "name": name,
                    "reason": "Duplicate name in file.",
                }
            )
            continue
        seen_in_file.add(key)

        is_active_raw = _as_bool(row.get("is_active"))
        is_active = True if is_active_raw is None else is_active_raw

        existing = (
            ProgramSpecialization.objects.filter(program=program, name__iexact=name)
            .order_by("id")
            .first()
        )
        if existing:
            changed = False
            if existing.name != name:
                existing.name = name
                changed = True
            if existing.is_active != is_active:
                existing.is_active = is_active
                changed = True
            if changed:
                existing.save(update_fields=["name", "is_active", "updated_at"])
                updated += 1
            else:
                skipped += 1
            continue

        try:
            ProgramSpecialization.objects.create(
                program=program,
                name=name,
                is_active=is_active,
            )
            created += 1
        except Exception as exc:  # pragma: no cover - defensive
            errors.append({"row": row_num, "name": name, "reason": str(exc)})

    return {
        "ok": True,
        "program_id": program.id,
        "program_name": program.name,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total_in_file": created + updated + skipped + len(errors),
    }
