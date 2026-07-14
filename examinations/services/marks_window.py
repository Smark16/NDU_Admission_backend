"""Marks-entry window resolution and enforcement."""
from __future__ import annotations

from django.utils import timezone

from accounts.super_admin import user_is_super_admin
from Programs.models import CourseUnit

from ..models import MarksEntryWindow
from ..permissions import user_can_access_examinations_office


def user_can_override_marks_window(user) -> bool:
    """Exam-office users can manage marks outside lecturer entry windows."""
    return bool(user and user.is_authenticated and (
        user_is_super_admin(user) or user_can_access_examinations_office(user)
    ))


def resolve_marks_entry_window(course_unit: CourseUnit) -> MarksEntryWindow | None:
    """
    Return the most specific active window for a course.

    Specificity order:
    1. Course-specific window
    2. Semester window
    3. Programme batch window
    """
    if not course_unit.program_batch_id:
        return None

    qs = MarksEntryWindow.objects.filter(
        is_active=True,
        program_batch_id=course_unit.program_batch_id,
    ).select_related("program_batch", "semester", "course_unit")

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


def marks_entry_status(course_unit: CourseUnit, *, user=None) -> dict:
    window = resolve_marks_entry_window(course_unit)
    now = timezone.now()
    override = user_can_override_marks_window(user)

    if window is None:
        return {
            "is_open": True,
            "can_enter": True,
            "override": override,
            "detail": "No marks-entry window configured; entry is open.",
            "window": None,
        }

    blockers = []
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
