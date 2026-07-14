"""Lecture attendance percentages and exam-sit thresholds."""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone as dj_tz

from .models import (
    CourseUnit,
    LectureAttendanceRecord,
    LectureAttendanceSession,
    StudentCourseUnitEnrollment,
)

# Present / late / excused count toward attendance %; absent does not.
ATTENDED_STATUSES = {
    LectureAttendanceRecord.STATUS_PRESENT,
    LectureAttendanceRecord.STATUS_LATE,
    LectureAttendanceRecord.STATUS_EXCUSED,
}

DEFAULT_MIN_ATTENDANCE_PERCENT = 75


def min_attendance_percent_to_sit_exam() -> float:
    raw = getattr(settings, "MIN_ATTENDANCE_PERCENT_TO_SIT_EXAM", DEFAULT_MIN_ATTENDANCE_PERCENT)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_MIN_ATTENDANCE_PERCENT)


def student_course_attendance_summary(student, course_unit: CourseUnit, *, as_of=None) -> dict:
    """
    Attendance % for one student on one course unit.

    Denominator = lecture sessions already taken for the course (up to as_of).
    Numerator = sessions where the student is present, late, or excused.
    If no sessions have been taken yet, percent is None and eligibility is not blocked.
    """
    as_of = as_of or dj_tz.localdate()
    sessions = list(
        LectureAttendanceSession.objects.filter(
            course_unit=course_unit,
            session_date__lte=as_of,
        ).order_by("session_date")
    )
    sessions_taken = len(sessions)
    if sessions_taken == 0:
        return {
            "course_unit_id": course_unit.id,
            "course_code": course_unit.code,
            "course_name": course_unit.name,
            "sessions_taken": 0,
            "sessions_attended": 0,
            "sessions_absent": 0,
            "sessions_unmarked": 0,
            "attendance_percent": None,
            "min_percent_required": min_attendance_percent_to_sit_exam(),
            "meets_threshold": True,
            "eligible_for_exam_by_attendance": True,
            "as_of": as_of.isoformat(),
        }

    records = {
        r.attendance_session_id: r
        for r in LectureAttendanceRecord.objects.filter(
            attendance_session__in=sessions,
            student=student,
        )
    }
    attended = 0
    absent = 0
    unmarked = 0
    for session in sessions:
        rec = records.get(session.id)
        if rec is None or not rec.status:
            unmarked += 1
            continue
        if rec.status in ATTENDED_STATUSES:
            attended += 1
        elif rec.status == LectureAttendanceRecord.STATUS_ABSENT:
            absent += 1
        else:
            unmarked += 1

    percent = round((attended / sessions_taken) * 100, 1)
    minimum = min_attendance_percent_to_sit_exam()
    meets = percent >= minimum
    return {
        "course_unit_id": course_unit.id,
        "course_code": course_unit.code,
        "course_name": course_unit.name,
        "sessions_taken": sessions_taken,
        "sessions_attended": attended,
        "sessions_absent": absent,
        "sessions_unmarked": unmarked,
        "attendance_percent": percent,
        "min_percent_required": minimum,
        "meets_threshold": meets,
        "eligible_for_exam_by_attendance": meets,
        "as_of": as_of.isoformat(),
    }


def student_attendance_summaries(student, *, as_of=None) -> list[dict]:
    """Summaries for all enrolled course units."""
    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(student=student, status="enrolled")
        .select_related("course_unit", "course_unit__semester")
        .order_by("course_unit__code")
    )
    return [
        student_course_attendance_summary(student, e.course_unit, as_of=as_of)
        for e in enrollments
    ]


def course_unit_student_attendance_map(course_unit: CourseUnit, student_ids, *, as_of=None) -> dict[int, dict]:
    """
    Batch attendance % for many students on one course unit.
    Returns {student_id: summary_dict} (same fields as student_course_attendance_summary).
    """
    as_of = as_of or dj_tz.localdate()
    student_ids = list(student_ids)
    minimum = min_attendance_percent_to_sit_exam()
    base = {
        "course_unit_id": course_unit.id,
        "course_code": course_unit.code,
        "course_name": course_unit.name,
        "min_percent_required": minimum,
        "as_of": as_of.isoformat(),
    }
    sessions = list(
        LectureAttendanceSession.objects.filter(
            course_unit=course_unit,
            session_date__lte=as_of,
        ).order_by("session_date")
    )
    sessions_taken = len(sessions)
    empty = {
        **base,
        "sessions_taken": 0,
        "sessions_attended": 0,
        "sessions_absent": 0,
        "sessions_unmarked": 0,
        "attendance_percent": None,
        "meets_threshold": True,
        "eligible_for_exam_by_attendance": True,
    }
    if sessions_taken == 0 or not student_ids:
        return {sid: dict(empty) for sid in student_ids}

    records = LectureAttendanceRecord.objects.filter(
        attendance_session__in=sessions,
        student_id__in=student_ids,
    ).only("attendance_session_id", "student_id", "status")
    by_student: dict[int, dict[int, str]] = {sid: {} for sid in student_ids}
    for rec in records:
        by_student.setdefault(rec.student_id, {})[rec.attendance_session_id] = rec.status

    out: dict[int, dict] = {}
    for sid in student_ids:
        attended = 0
        absent = 0
        unmarked = 0
        status_map = by_student.get(sid) or {}
        for session in sessions:
            status = status_map.get(session.id)
            if not status:
                unmarked += 1
            elif status in ATTENDED_STATUSES:
                attended += 1
            elif status == LectureAttendanceRecord.STATUS_ABSENT:
                absent += 1
            else:
                unmarked += 1
        percent = round((attended / sessions_taken) * 100, 1)
        meets = percent >= minimum
        out[sid] = {
            **base,
            "sessions_taken": sessions_taken,
            "sessions_attended": attended,
            "sessions_absent": absent,
            "sessions_unmarked": unmarked,
            "attendance_percent": percent,
            "meets_threshold": meets,
            "eligible_for_exam_by_attendance": meets,
        }
    return out


def faculty_attendance_report(*, course_units, as_of=None) -> dict:
    """
    Aggregate attendance for course units (caller applies faculty/batch scope).

    Returns per-course averages and students below the exam-sit threshold.
    """
    as_of = as_of or dj_tz.localdate()
    minimum = min_attendance_percent_to_sit_exam()
    course_summaries = []
    below_rows = []

    for cu in course_units:
        enrolled = list(
            StudentCourseUnitEnrollment.objects.filter(course_unit=cu, status="enrolled")
            .select_related("student")
            .order_by("student__reg_no", "student__student_id")
        )
        student_ids = [e.student_id for e in enrolled]
        stats_map = course_unit_student_attendance_map(cu, student_ids, as_of=as_of)
        by_student = {e.student_id: e.student for e in enrolled}

        percents = [
            row["attendance_percent"]
            for row in stats_map.values()
            if row.get("attendance_percent") is not None
        ]
        sessions_taken = 0
        if stats_map:
            sessions_taken = next(iter(stats_map.values())).get("sessions_taken", 0)

        below_count = 0
        for sid, row in stats_map.items():
            if not row.get("sessions_taken") or row.get("meets_threshold"):
                continue
            below_count += 1
            st = by_student.get(sid)
            if not st:
                continue
            below_rows.append(
                {
                    "student_id": st.id,
                    "reg_no": st.reg_no or "",
                    "student_number": st.student_id or "",
                    "name": st.full_name,
                    "course_unit_id": cu.id,
                    "course_code": cu.code,
                    "course_name": cu.name,
                    "attendance_percent": row.get("attendance_percent"),
                    "sessions_attended": row.get("sessions_attended", 0),
                    "sessions_taken": row.get("sessions_taken", 0),
                    "min_percent_required": minimum,
                }
            )

        pb = getattr(cu, "program_batch", None) or (
            cu.semester.program_batch
            if getattr(cu, "semester_id", None) and getattr(cu, "semester", None)
            else None
        )
        program = pb.program if pb and pb.program_id else None
        course_summaries.append(
            {
                "course_unit_id": cu.id,
                "course_code": cu.code,
                "course_name": cu.name,
                "program_batch_id": pb.id if pb else None,
                "program_batch_name": pb.name if pb else "",
                "program_name": program.name if program else "",
                "students_enrolled": len(enrolled),
                "sessions_taken": sessions_taken,
                "average_attendance_percent": (
                    round(sum(percents) / len(percents), 1) if percents else None
                ),
                "below_threshold_count": below_count,
                "min_percent_required": minimum,
            }
        )

    course_summaries.sort(key=lambda r: (r["course_code"], r["course_name"]))
    below_rows.sort(
        key=lambda r: (r["course_code"], r["attendance_percent"] or 0, r["name"])
    )
    return {
        "as_of": as_of.isoformat(),
        "min_percent_required": minimum,
        "courses": course_summaries,
        "below_threshold": below_rows,
        "below_threshold_count": len(below_rows),
        "courses_count": len(course_summaries),
    }
