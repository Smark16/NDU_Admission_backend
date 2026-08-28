"""Bulk preview and apply marks-entry windows across many programme batches."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils import timezone

from admissions.faculty_scope import filter_program_batches_for_user
from Programs.models import ProgramBatch


@dataclass
class BulkFilters:
    academic_year: str | None = None
    faculty_id: int | None = None
    academic_level_id: int | None = None
    campus_id: int | None = None


def _parse_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bulk_filters(data: dict) -> BulkFilters:
    return BulkFilters(
        academic_year=(data.get("academic_year") or "").strip() or None,
        faculty_id=_parse_int(data.get("faculty_id")),
        academic_level_id=_parse_int(data.get("academic_level_id")),
        campus_id=_parse_int(data.get("campus_id")),
    )


def _batch_level_windows():
    from examinations.models import MarksEntryWindow

    return MarksEntryWindow.objects.filter(
        semester__isnull=True,
        course_unit__isnull=True,
    )


def _window_status_key(window, *, now=None) -> str:
    """none | inactive | scheduled | open | closed"""
    if window is None:
        return "none"
    if not window.is_active:
        return "inactive"
    now = now or timezone.now()
    if window.opens_at and now < window.opens_at:
        return "scheduled"
    if window.closes_at and now > window.closes_at:
        return "closed"
    return "open"


def _plan_action(status_key: str, *, skip_open: bool) -> str:
    if status_key == "open":
        return "skip" if skip_open else "skip"
    if status_key == "none":
        return "create"
    return "open"


def filtered_batches_queryset(user, filters: BulkFilters):
    qs = (
        ProgramBatch.objects.filter(is_active=True, program__is_active=True)
        .select_related("program", "program__faculty", "program__academic_level")
        .order_by("program__name", "name")
    )
    qs = filter_program_batches_for_user(qs, user)

    if filters.academic_year:
        qs = qs.filter(academic_year__iexact=filters.academic_year)
    if filters.faculty_id:
        qs = qs.filter(program__faculty_id=filters.faculty_id)
    if filters.academic_level_id:
        qs = qs.filter(program__academic_level_id=filters.academic_level_id)
    if filters.campus_id:
        qs = qs.filter(program__campuses__id=filters.campus_id)

    return qs.distinct()


def distinct_academic_years(user) -> list[str]:
    qs = filtered_batches_queryset(user, BulkFilters())
    years = (
        qs.exclude(academic_year="")
        .values_list("academic_year", flat=True)
        .distinct()
        .order_by("-academic_year")
    )
    return [y for y in years if y]


def _pick_batch_window(windows_by_batch: dict[int, list], batch_id: int):
    candidates = windows_by_batch.get(batch_id) or []
    if not candidates:
        return None
    active = [w for w in candidates if w.is_active]
    pool = active or candidates
    return sorted(pool, key=lambda w: w.updated_at, reverse=True)[0]


def preview_bulk_marks_windows(user, filters: BulkFilters, *, skip_open: bool = True) -> dict[str, Any]:
    batches = list(filtered_batches_queryset(user, filters))
    batch_ids = [b.id for b in batches]

    windows_by_batch: dict[int, list] = {}
    if batch_ids:
        for w in _batch_level_windows().filter(program_batch_id__in=batch_ids).select_related(
            "program_batch"
        ):
            windows_by_batch.setdefault(w.program_batch_id, []).append(w)

    now = timezone.now()
    rows = []
    summary = {"total": 0, "create": 0, "open": 0, "skip": 0}

    for batch in batches:
        window = _pick_batch_window(windows_by_batch, batch.id)
        status_key = _window_status_key(window, now=now)
        action = _plan_action(status_key, skip_open=skip_open)
        summary["total"] += 1
        summary[action] += 1

        program = batch.program
        rows.append(
            {
                "batch_id": batch.id,
                "batch_name": batch.name,
                "academic_year": batch.academic_year or "",
                "program_id": program.id,
                "program_name": program.name,
                "program_code": program.code,
                "program_short_form": program.short_form,
                "faculty_name": program.faculty.name if program.faculty_id else None,
                "academic_level_name": (
                    program.academic_level.name if program.academic_level_id else None
                ),
                "window_id": window.id if window else None,
                "window_status": status_key,
                "planned_action": action,
                "window_name": window.name if window else None,
            }
        )

    return {
        "filters": {
            "academic_year": filters.academic_year,
            "faculty_id": filters.faculty_id,
            "academic_level_id": filters.academic_level_id,
            "campus_id": filters.campus_id,
        },
        "academic_years": distinct_academic_years(user),
        "summary": summary,
        "rows": rows,
    }


def _default_window_name(batch: ProgramBatch, name_prefix: str | None) -> str:
    prefix = (name_prefix or "").strip()
    base = f"{batch.program.short_form or batch.program.code} — {batch.name}"
    if prefix:
        return f"{prefix} · {base}"
    return f"{base} marks entry"


def apply_bulk_marks_windows(
    user,
    filters: BulkFilters,
    *,
    name_prefix: str | None = None,
    opens_at=None,
    closes_at=None,
    notes: str = "",
    skip_open: bool = True,
) -> dict[str, Any]:
    from examinations.models import MarksEntryWindow

    preview = preview_bulk_marks_windows(user, filters, skip_open=skip_open)
    now = timezone.now()
    created = 0
    opened = 0
    skipped = 0
    errors: list[str] = []

    actionable = [r for r in preview["rows"] if r["planned_action"] in ("create", "open")]

    with transaction.atomic():
        for row in actionable:
            batch = ProgramBatch.objects.select_related("program").get(pk=row["batch_id"])
            action = row["planned_action"]
            try:
                if action == "create":
                    MarksEntryWindow.objects.create(
                        name=_default_window_name(batch, name_prefix),
                        program_batch=batch,
                        opens_at=opens_at or now,
                        closes_at=closes_at,
                        is_active=True,
                        notes=notes,
                        created_by=user,
                    )
                    created += 1
                elif action == "open":
                    window = _pick_batch_window(
                        {
                            w.program_batch_id: [w]
                            for w in _batch_level_windows().filter(program_batch_id=batch.id)
                        },
                        batch.id,
                    )
                    if window is None:
                        MarksEntryWindow.objects.create(
                            name=_default_window_name(batch, name_prefix),
                            program_batch=batch,
                            opens_at=opens_at or now,
                            closes_at=closes_at,
                            is_active=True,
                            notes=notes,
                            created_by=user,
                        )
                        created += 1
                    else:
                        window.is_active = True
                        if opens_at is not None:
                            window.opens_at = opens_at
                        elif window.opens_at is None or window.opens_at > now:
                            window.opens_at = now
                        if closes_at is not None:
                            window.closes_at = closes_at
                        elif window.closes_at and window.closes_at <= now:
                            window.closes_at = None
                        if notes:
                            window.notes = notes
                        window.closed_by = None
                        window.closed_at = None
                        window.save(
                            update_fields=[
                                "is_active",
                                "opens_at",
                                "closes_at",
                                "notes",
                                "closed_by",
                                "closed_at",
                                "updated_at",
                            ]
                        )
                        opened += 1
                else:
                    skipped += 1
            except Exception as exc:
                errors.append(f"{batch.program.code} / {batch.name}: {exc}")

        skipped += preview["summary"]["skip"]

    return {
        "created": created,
        "opened": opened,
        "skipped": skipped,
        "errors": errors,
        "processed": len(actionable),
    }
