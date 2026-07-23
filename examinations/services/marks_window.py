"""Marks-entry window resolution and enforcement."""
from __future__ import annotations

import logging

from django.db import DatabaseError
from django.db.models import QuerySet
from django.utils import timezone

from accounts.super_admin import user_is_super_admin
from Programs.models import CourseUnit

from ..models import MarksEntryWindow
from ..permissions import user_can_access_examinations_office

logger = logging.getLogger(__name__)


def user_can_override_marks_window(user) -> bool:
    """Exam-office users can manage marks outside lecturer entry windows."""
    return bool(
        user
        and user.is_authenticated
        and (user_is_super_admin(user) or user_can_access_examinations_office(user))
    )


def _pick_most_specific(qs: QuerySet[MarksEntryWindow], course_unit: CourseUnit) -> MarksEntryWindow | None:
    """Prefer course → semester → batch scope; newest updated wins within a scope."""
    course_window = qs.filter(course_unit_id=course_unit.id).order_by("-updated_at").first()
    if course_window:
        return course_window

    if course_unit.semester_id:
        semester_window = (
            qs.filter(semester_id=course_unit.semester_id, course_unit__isnull=True)
            .order_by("-updated_at")
            .first()
        )
        if semester_window:
            return semester_window

    return (
        qs.filter(semester__isnull=True, course_unit__isnull=True)
        .order_by("-updated_at")
        .first()
    )


def resolve_marks_entry_window(course_unit: CourseUnit) -> MarksEntryWindow | None:
    """
    Return the most specific window for a course.

    Prefers an active window. If none is active at that scope, falls back to the
    matching inactive window so deactivation still closes lecturer entry
    (instead of treating "no active window" as permanently open).
    """
    if not course_unit.program_batch_id:
        return None

    try:
        base = MarksEntryWindow.objects.filter(
            program_batch_id=course_unit.program_batch_id,
        ).select_related("program_batch", "semester", "course_unit")

        active = _pick_most_specific(base.filter(is_active=True), course_unit)
        if active:
            return active

        # Deactivated / soft-deleted window still governs this scope → closed.
        return _pick_most_specific(base.filter(is_active=False), course_unit)
    except DatabaseError:
        # Table/migration missing on some environments — treat as no window.
        logger.exception(
            "MarksEntryWindow lookup failed for course_unit_id=%s",
            getattr(course_unit, "pk", None),
        )
        return None


def marks_entry_status(course_unit: CourseUnit, *, user=None) -> dict:
    try:
        window = resolve_marks_entry_window(course_unit)
        override = user_can_override_marks_window(user)
    except Exception:
        logger.exception(
            "marks_entry_status failed for course_unit_id=%s",
            getattr(course_unit, "pk", None),
        )
        override = user_can_override_marks_window(user)
        return {
            "is_open": False,
            "can_enter": override,
            "override": override,
            "detail": "Marks-entry window status unavailable; entry closed.",
            "window": None,
        }

    now = timezone.now()

    if window is None:
        # Lecturers cannot enter until exam office opens a window.
        return {
            "is_open": False,
            "can_enter": override,
            "override": override,
            "detail": "No marks-entry window configured; entry is closed.",
            "window": None,
        }

    blockers: list[str] = []
    if not window.is_active:
        blockers.append("Marks entry window is deactivated.")
    if window.opens_at and now < window.opens_at:
        blockers.append("Marks entry has not opened yet.")
    if window.closes_at and now > window.closes_at:
        blockers.append("Marks entry is closed.")

    is_open = not blockers
    return {
        "is_open": is_open,
        "can_enter": is_open or override,
        "override": override and not is_open,
        "detail": " ".join(blockers) if blockers else "Marks entry is open.",
        "window": {
            "id": window.id,
            "name": window.name,
            "scope": (
                "course"
                if window.course_unit_id
                else "semester"
                if window.semester_id
                else "batch"
            ),
            "opens_at": window.opens_at.isoformat() if window.opens_at else None,
            "closes_at": window.closes_at.isoformat() if window.closes_at else None,
            "is_active": window.is_active,
        },
    }


def assert_marks_entry_allowed(course_unit: CourseUnit, *, user) -> None:
    status = marks_entry_status(course_unit, user=user)
    if not status["can_enter"]:
        raise PermissionError(status["detail"] or "Marks entry is closed.")
