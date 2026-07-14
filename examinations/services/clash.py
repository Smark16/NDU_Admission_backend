"""Exam session clash and capacity checks (warn mode — callers may force)."""
from __future__ import annotations

from datetime import time
from typing import Any

from Programs.models import StudentCourseUnitEnrollment

from ..models import CourseUnitResult, ExamSession


def _times_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Treat missing end as end-of-day and missing start as start-of-day for overlap."""
    a0 = a_start or time.min
    a1 = a_end or time.max
    b0 = b_start or time.min
    b1 = b_end or time.max
    return a0 < b1 and b0 < a1


def candidate_student_ids(course_unit, session_type: str) -> set[int]:
    """Student PKs that would sit this course for the given session type."""
    if session_type in (ExamSession.TYPE_RETAKE, ExamSession.TYPE_SUPPLEMENTARY):
        qs = StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            course_result__status=CourseUnitResult.STATUS_PUBLISHED,
            course_result__is_pass=False,
            registration_date__isnull=False,
        )
    else:
        qs = StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            status="enrolled",
            registration_date__isnull=False,
        )
    return set(qs.values_list("student_id", flat=True))


def candidate_count(course_unit, session_type: str) -> int:
    return len(candidate_student_ids(course_unit, session_type))


def effective_capacity(session: ExamSession | None = None, *, venue=None, max_candidates=None) -> int | None:
    """Stricter of max_candidates and venue.capacity when both set."""
    limits: list[int] = []
    mc = max_candidates if max_candidates is not None else (session.max_candidates if session else None)
    v = venue if venue is not None else (session.venue if session else None)
    if mc:
        limits.append(int(mc))
    if v is not None and getattr(v, "capacity", None):
        limits.append(int(v.capacity))
    return min(limits) if limits else None


def evaluate_session_issues(
    *,
    course_unit,
    exam_date,
    start_time=None,
    end_time=None,
    venue=None,
    max_candidates=None,
    session_type: str = ExamSession.TYPE_REGULAR,
    exclude_session_id: int | None = None,
    invigilator_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """Return list of conflict/capacity warning dicts (empty if clean)."""
    conflicts: list[dict[str, Any]] = []

    others = ExamSession.objects.filter(exam_date=exam_date).select_related(
        "course_unit", "venue"
    )
    if exclude_session_id:
        others = others.exclude(pk=exclude_session_id)
    others = list(others)

    # Room clashes
    if venue is not None and not getattr(venue, "allows_parallel_sessions", False):
        for other in others:
            if other.venue_id != venue.pk:
                continue
            if _times_overlap(start_time, end_time, other.start_time, other.end_time):
                conflicts.append(
                    {
                        "type": "room",
                        "message": (
                            f"Room clash with {other.course_unit.code} "
                            f"({other.start_time or '—'}–{other.end_time or '—'})"
                        ),
                        "other_session_id": other.id,
                        "other_course_code": other.course_unit.code,
                    }
                )

    # Student clashes
    my_students = candidate_student_ids(course_unit, session_type)
    if my_students:
        for other in others:
            if other.course_unit_id == course_unit.id:
                continue
            if not _times_overlap(start_time, end_time, other.start_time, other.end_time):
                continue
            other_students = candidate_student_ids(other.course_unit, other.session_type)
            overlap = my_students & other_students
            if overlap:
                conflicts.append(
                    {
                        "type": "student",
                        "message": (
                            f"{len(overlap)} student(s) also scheduled for "
                            f"{other.course_unit.code} at overlapping time"
                        ),
                        "other_session_id": other.id,
                        "other_course_code": other.course_unit.code,
                        "overlap_count": len(overlap),
                    }
                )

    # Invigilator overlaps
    if invigilator_ids:
        inv_set = set(invigilator_ids)
        for other in others:
            try:
                other_ids = set(other.invigilators.values_list("id", flat=True))
            except Exception:
                other_ids = set()
            shared = inv_set & other_ids
            if not shared:
                continue
            if not _times_overlap(start_time, end_time, other.start_time, other.end_time):
                continue
            conflicts.append(
                {
                    "type": "invigilator",
                    "message": (
                        f"{len(shared)} invigilator(s) already assigned to "
                        f"{other.course_unit.code} at overlapping time"
                    ),
                    "other_session_id": other.id,
                    "other_course_code": other.course_unit.code,
                }
            )

    # Capacity
    cap = effective_capacity(venue=venue, max_candidates=max_candidates)
    count = candidate_count(course_unit, session_type)
    if cap is not None and count > cap:
        conflicts.append(
            {
                "type": "capacity",
                "message": f"Candidate count ({count}) exceeds effective capacity ({cap})",
                "candidate_count": count,
                "effective_capacity": cap,
            }
        )

    return conflicts


def wants_force(data) -> bool:
    raw = data.get("force") if hasattr(data, "get") else False
    return str(raw).lower() in ("1", "true", "yes")
