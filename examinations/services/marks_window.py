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


def _candidates_at_most_specific_scope(
    qs: QuerySet[MarksEntryWindow], course_unit: CourseUnit
) -> QuerySet[MarksEntryWindow]:
    """
    All windows (any component) at the single most-specific scope that has at
    least one window — course, else semester, else batch. Narrower scopes
    override wider ones as a whole, independent of which component they cover;
    a course-level CA-only window must not let an exam check leak through to
    a wider batch-level window.
    """
    course_qs = qs.filter(course_unit_id=course_unit.id)
    if course_qs.exists():
        return course_qs

    if course_unit.semester_id:
        semester_qs = qs.filter(semester_id=course_unit.semester_id, course_unit__isnull=True)
        if semester_qs.exists():
            return semester_qs

    return qs.filter(semester__isnull=True, course_unit__isnull=True)


def _pick_component_window(
    candidates: QuerySet[MarksEntryWindow], component: str
) -> MarksEntryWindow | None:
    """Within one scope's candidates, prefer an exact-component window over a 'both' one."""
    matching = candidates.filter(component__in=(component, MarksEntryWindow.COMPONENT_BOTH))
    exact = matching.filter(component=component).order_by("-updated_at").first()
    if exact:
        return exact
    return matching.filter(component=MarksEntryWindow.COMPONENT_BOTH).order_by("-updated_at").first()


def resolve_marks_entry_window(
    course_unit: CourseUnit, *, component: str = MarksEntryWindow.COMPONENT_BOTH
) -> MarksEntryWindow | None:
    """
    Return the window covering this component ('ca' or 'exam') for a course.

    Resolution is scope-first: find the most specific scope with any active
    window, then use its component-matching window if one exists there. If
    that scope has windows but none cover this component, the component is
    closed *at that scope* — we do not fall back to a wider scope, so a
    narrower CA-only (or exam-only) window can genuinely close the other
    component instead of silently inheriting a wider "both" window.
    """
    if not course_unit.program_batch_id:
        return None

    try:
        base = MarksEntryWindow.objects.filter(
            program_batch_id=course_unit.program_batch_id,
        ).select_related("program_batch", "semester", "course_unit")

        active_scope = _candidates_at_most_specific_scope(base.filter(is_active=True), course_unit)
        window = _pick_component_window(active_scope, component)
        if window:
            return window
        if active_scope.exists():
            # This scope has an active window, just not for this component —
            # closed here, not a fallback to a wider scope.
            return None

        # No active window anywhere for this course — check the matching
        # inactive scope so an explicit deactivation still reads as closed
        # instead of "no window = open".
        inactive_scope = _candidates_at_most_specific_scope(base.filter(is_active=False), course_unit)
        return _pick_component_window(inactive_scope, component)
    except DatabaseError:
        # Table/migration missing on some environments — treat as no window.
        logger.exception(
            "MarksEntryWindow lookup failed for course_unit_id=%s",
            getattr(course_unit, "pk", None),
        )
        return None


def _component_status(course_unit: CourseUnit, *, component: str, override: bool) -> dict:
    window = resolve_marks_entry_window(course_unit, component=component)
    now = timezone.now()

    if window is None:
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
            "component": window.component,
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


def marks_entry_status(course_unit: CourseUnit, *, user=None) -> dict:
    """
    Per-component status (ca / exam) plus a combined view for older consumers.

    Combined `is_open`/`can_enter` are true when EITHER component is open, so
    existing callers that only checked the top level still see entry as
    possible; the per-component detail is what actually gates each field.
    """
    override = user_can_override_marks_window(user)
    try:
        ca = _component_status(course_unit, component=MarksEntryWindow.COMPONENT_CA, override=override)
        exam = _component_status(course_unit, component=MarksEntryWindow.COMPONENT_EXAM, override=override)
    except Exception:
        logger.exception(
            "marks_entry_status failed for course_unit_id=%s",
            getattr(course_unit, "pk", None),
        )
        blocked = {
            "is_open": False,
            "can_enter": override,
            "override": override,
            "detail": "Marks-entry window status unavailable; entry closed.",
            "window": None,
        }
        return {"ca": blocked, "exam": blocked, **blocked}

    combined_detail = ca["detail"] if ca["detail"] == exam["detail"] else (
        f"CA: {ca['detail']} Exam: {exam['detail']}"
    )
    return {
        "ca": ca,
        "exam": exam,
        "is_open": ca["is_open"] or exam["is_open"],
        "can_enter": ca["can_enter"] or exam["can_enter"],
        "override": ca["override"] or exam["override"],
        "detail": combined_detail,
        "window": ca["window"] or exam["window"],
    }


def assert_marks_entry_allowed(
    course_unit: CourseUnit, *, user, component: str = MarksEntryWindow.COMPONENT_BOTH
) -> None:
    """
    component: 'ca' or 'exam' to check one field; 'both' checks both are open
    (used by callers that don't yet distinguish which field they're writing).
    """
    override = user_can_override_marks_window(user)
    if component == MarksEntryWindow.COMPONENT_BOTH:
        ca = _component_status(course_unit, component=MarksEntryWindow.COMPONENT_CA, override=override)
        exam = _component_status(course_unit, component=MarksEntryWindow.COMPONENT_EXAM, override=override)
        if not ca["can_enter"]:
            raise PermissionError(ca["detail"] or "CA marks entry is closed.")
        if not exam["can_enter"]:
            raise PermissionError(exam["detail"] or "Exam marks entry is closed.")
        return

    status = _component_status(course_unit, component=component, override=override)
    if not status["can_enter"]:
        raise PermissionError(status["detail"] or "Marks entry is closed.")
