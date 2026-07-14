"""Lecture attendance APIs for lecturers and faculty/admins."""
from __future__ import annotations

from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone as dj_tz
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import (
    assert_course_unit_access,
    filter_course_units_for_user,
    filter_lecture_attendance_sessions_for_user,
    user_faculty_ids,
)

from .attendance_pdf import (
    build_attendance_sheet_context,
    render_attendance_sheet_pdf,
    safe_attendance_pdf_filename,
)
from .models import (
    CourseUnit,
    LectureAttendanceRecord,
    LectureAttendanceSession,
    StudentCourseUnitEnrollment,
    TimetableSession,
)
from .permissions import LectureAttendanceAdminPermission
from .timetable_utils import session_location_label, weekday_dates_in_range


STATUS_LABELS = dict(LectureAttendanceRecord.STATUS_CHOICES)
VALID_STATUSES = set(STATUS_LABELS)


def _parse_date(value):
    if not value:
        return None
    if hasattr(value, "year"):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _user_is_course_lecturer(user, course_unit: CourseUnit) -> bool:
    return course_unit.lecturers.filter(pk=user.pk).exists()


def _assert_lecturer_course_access(user, course_unit: CourseUnit) -> None:
    from rest_framework.exceptions import PermissionDenied

    if not _user_is_course_lecturer(user, course_unit):
        raise PermissionDenied("You are not assigned to teach this course unit.")


def _assert_admin_course_access(user, course_unit: CourseUnit) -> None:
    """Faculty scope via program_batch, falling back to semester.program_batch."""
    assert_course_unit_access(user, course_unit)


def _assert_attendance_admin_write(user) -> None:
    from rest_framework.exceptions import PermissionDenied
    from accounts.super_admin import user_is_super_admin
    from accounts.erp_drf_permissions import user_has_any_erp_perm
    from admissions.faculty_scope import user_is_faculty_admin, user_is_faculty_dean

    if user_is_super_admin(user):
        return
    if user_is_faculty_admin(user) or user_is_faculty_dean(user):
        return
    if user_has_any_erp_perm(
        user,
        "access_academics",
        "manage_program_scheduling",
        "manage_academic_enrollment",
    ):
        return
    if user.has_perm("Programs.manage_faculty_lecture_attendance"):
        return
    if user.has_perm("Programs.view_lectureattendancesession"):
        return
    raise PermissionDenied("You do not have permission to manage lecture attendance.")


def _course_unit_qs():
    return CourseUnit.objects.select_related(
        "semester",
        "semester__program_batch",
        "program_batch",
        "program_batch__program",
        "program_batch__program__faculty",
    ).prefetch_related("lecturers")


def _get_course_unit(course_unit_id: int) -> CourseUnit | None:
    try:
        return _course_unit_qs().get(pk=course_unit_id, is_active=True)
    except CourseUnit.DoesNotExist:
        return None


def _parse_int(value):
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _filter_course_units_by_program_batch(qs, program_batch_id: int | None):
    if not program_batch_id:
        return qs
    return qs.filter(
        Q(program_batch_id=program_batch_id)
        | Q(semester__program_batch_id=program_batch_id)
    )


def _filter_sessions_by_program_batch(qs, program_batch_id: int | None):
    if not program_batch_id:
        return qs
    return qs.filter(
        Q(course_unit__program_batch_id=program_batch_id)
        | Q(course_unit__semester__program_batch_id=program_batch_id)
    )


def _programme_batch(course_unit: CourseUnit):
    return course_unit.program_batch or (
        course_unit.semester.program_batch if course_unit.semester_id else None
    )


def _serialize_course_unit(course_unit: CourseUnit) -> dict:
    program_batch = _programme_batch(course_unit)
    program = program_batch.program if program_batch else None
    semester = course_unit.semester
    return {
        "course_unit_id": course_unit.id,
        "course_code": course_unit.code,
        "course_name": course_unit.name,
        "semester": {
            "id": semester.id if semester else None,
            "name": semester.name if semester else None,
        }
        if semester
        else None,
        "program_batch": {
            "id": program_batch.id if program_batch else None,
            "name": program_batch.name if program_batch else None,
        }
        if program_batch
        else None,
        "program": {
            "id": program.id if program else None,
            "name": program.name if program else None,
            "faculty_id": program.faculty_id if program else None,
            "faculty_name": program.faculty.name if program and program.faculty_id else None,
        }
        if program
        else None,
        "lecturers": [
            {"id": u.id, "name": u.get_full_name() or u.username, "email": u.email}
            for u in course_unit.lecturers.all()
        ],
        "students_count": StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit, status="enrolled"
        ).count(),
    }


def _find_attendance_session(course_unit, session_date, timetable_session=None):
    """Locate the attendance register for a course meeting (slot-aware)."""
    qs = LectureAttendanceSession.objects.filter(
        course_unit=course_unit,
        session_date=session_date,
    ).select_related("taken_by", "timetable_session", "course_unit")
    if timetable_session is not None:
        return qs.filter(timetable_session=timetable_session).first()
    # Prefer an unscoped (no-slot) row when no slot was specified.
    noslot = qs.filter(timetable_session__isnull=True).first()
    if noslot:
        return noslot
    # Legacy / single-slot day: only one row exists.
    if qs.count() == 1:
        return qs.first()
    return None


def _get_or_create_attendance_session(
    *,
    course_unit,
    session_date,
    timetable_session=None,
    defaults: dict | None = None,
):
    defaults = defaults or {}
    lookup = {
        "course_unit": course_unit,
        "session_date": session_date,
        "timetable_session": timetable_session,
    }
    return LectureAttendanceSession.objects.select_for_update().get_or_create(
        **lookup,
        defaults=defaults,
    )


def _resolve_timetable_slot_id(raw_tid) -> TimetableSession | None:
    if raw_tid in (None, "", 0, "0"):
        return None
    try:
        tid = int(raw_tid)
    except (TypeError, ValueError):
        raise ValueError("timetable_session_id must be an integer.")
    slot = (
        TimetableSession.objects.filter(pk=tid, is_active=True)
        .select_related("course_unit", "venue", "venue__campus")
        .first()
    )
    if not slot:
        raise ValueError("Timetable session not found.")
    return slot


def _match_timetable_session(course_unit: CourseUnit, session_date):
    """Best-effort single match when no timetable_session_id is provided."""
    fixed = list(
        TimetableSession.objects.filter(
            course_unit=course_unit,
            is_active=True,
            is_published=True,
            session_date=session_date,
        )
        .select_related("venue", "venue__campus")
        .order_by("start_time")
    )
    if len(fixed) == 1:
        return fixed[0]
    if len(fixed) > 1:
        return None
    # Weekly templates for this weekday
    weekday = session_date.weekday() + 1
    weekly = list(
        TimetableSession.objects.filter(
            course_unit=course_unit,
            is_active=True,
            is_published=True,
            session_date__isnull=True,
            day_of_week=weekday,
        )
        .select_related("venue", "venue__campus")
        .order_by("start_time")
    )
    if len(weekly) == 1:
        return weekly[0]
    return None


def _lecturer_assigned_course_unit_ids(user) -> list[int]:
    """Course units this user is assigned to teach (source of truth for lecturer scope)."""
    return list(
        user.course_units.filter(is_active=True).values_list("id", flat=True).distinct()
    )


def _get_lecturer_timetable_slot(user, timetable_session_id) -> TimetableSession:
    try:
        tid = int(timetable_session_id)
    except (TypeError, ValueError):
        raise ValueError("timetable_session_id is required.")
    assigned_ids = _lecturer_assigned_course_unit_ids(user)
    slot = (
        TimetableSession.objects.filter(
            pk=tid,
            is_active=True,
            course_unit_id__in=assigned_ids,
        )
        .select_related(
            "course_unit",
            "course_unit__semester",
            "venue",
            "venue__campus",
        )
        .prefetch_related("course_unit__lecturers")
        .first()
    )
    if not slot:
        raise ValueError("Timetable class not found or not assigned to you.")
    _assert_lecturer_course_access(user, slot.course_unit)
    return slot


def _meeting_date_for_slot(slot: TimetableSession, preferred_date=None):
    """Resolve the calendar date for attendance from a timetable slot."""
    if preferred_date:
        return preferred_date
    if slot.session_date:
        return slot.session_date
    today = dj_tz.localdate()
    if slot.day_of_week == today.weekday() + 1:
        return today
    raise ValueError(
        "This timetable class has no fixed date. Pick a scheduled date from the list, "
        "or ask admin to set session dates on the timetable."
    )


def _lecturer_schedule_meetings(user, *, from_date=None, to_date=None) -> list[dict]:
    """
    Build attendance meetings for this lecturer on the selected day(s).

    Default is today only (date-sensitive). Weekly timetable templates only
    expand onto dates that match their day_of_week within the range.
    """
    today = dj_tz.localdate()
    # Date-sensitive default: only today's classes for capture.
    start = from_date or today
    end = to_date or start
    if end < start:
        start, end = end, start

    assigned_ids = _lecturer_assigned_course_unit_ids(user)
    if not assigned_ids:
        return []

    slots = list(
        TimetableSession.objects.filter(
            is_active=True,
            is_published=True,
            course_unit_id__in=assigned_ids,
        )
        .select_related(
            "course_unit",
            "course_unit__semester",
            "venue",
            "venue__campus",
        )
        .distinct()
        .order_by("session_date", "day_of_week", "start_time", "course_unit__code")
    )

    meetings: list[dict] = []
    for slot in slots:
        dates: list = []
        if slot.session_date:
            # Fixed-date slot: only if it falls on the selected day/range.
            if start <= slot.session_date <= end:
                dates = [slot.session_date]
        else:
            # Weekly template: only dates in range whose weekday matches the slot.
            semester = getattr(slot.course_unit, "semester", None)
            sem_start = getattr(semester, "start_date", None) if semester else None
            sem_end = getattr(semester, "end_date", None) if semester else None
            range_start = max(start, sem_start) if sem_start else start
            range_end = min(end, sem_end) if sem_end else end
            if range_start <= range_end:
                dates = weekday_dates_in_range(range_start, range_end, slot.day_of_week)

        location = session_location_label(slot)
        for meeting_date in dates:
            # Extra guard: weekday must match the timetable day.
            if meeting_date.weekday() + 1 != slot.day_of_week:
                continue
            att = _find_attendance_session(slot.course_unit, meeting_date, timetable_session=slot)
            meetings.append(
                {
                    "key": f"{slot.id}:{meeting_date.isoformat()}",
                    "timetable_session_id": slot.id,
                    "course_unit_id": slot.course_unit_id,
                    "course_code": slot.course_unit.code,
                    "course_name": slot.course_unit.name,
                    "session_date": meeting_date.isoformat(),
                    "day_of_week": slot.day_of_week,
                    "day_label": dict(TimetableSession.DAY_CHOICES).get(slot.day_of_week, ""),
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                    "location": location,
                    "session_type": slot.session_type,
                    "delivery_mode": slot.delivery_mode or "on_campus",
                    "is_today": meeting_date == today,
                    "attendance_session_id": att.id if att else None,
                    "check_in_open": bool(att and att.student_check_in_open),
                    "attendance_taken": bool(att),
                    "is_locked": bool(att and att.locked_at),
                }
            )

    meetings.sort(key=lambda m: (m["session_date"], m["start_time"], m["course_code"]))
    return meetings


def _resolve_timetable_from_request(user, data_or_params) -> TimetableSession | None:
    raw = data_or_params.get("timetable_session_id")
    if raw in (None, "", 0, "0"):
        return None
    return _get_lecturer_timetable_slot(user, raw)


def _enrolled_students(course_unit: CourseUnit):
    enrollments = (
        StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            status="enrolled",
        )
        .select_related("student", "student__application")
        .order_by("student__reg_no", "student__student_id")
    )
    return [e.student for e in enrollments]


def _check_in_payload(session: LectureAttendanceSession | None) -> dict:
    if not session:
        return {
            "check_in_open": False,
            "check_in_opened_at": None,
            "check_in_closes_at": None,
            "check_in_closed_at": None,
            "check_in_duration_minutes": 30,
            "checked_in_count": 0,
            "has_qr_token": False,
        }
    checked_in = session.records.filter(
        status__in=[
            LectureAttendanceRecord.STATUS_PRESENT,
            LectureAttendanceRecord.STATUS_LATE,
            LectureAttendanceRecord.STATUS_EXCUSED,
        ]
    ).count()
    return {
        "check_in_open": session.student_check_in_open,
        "check_in_opened_at": session.check_in_opened_at.isoformat() if session.check_in_opened_at else None,
        "check_in_closes_at": session.check_in_closes_at.isoformat() if session.check_in_closes_at else None,
        "check_in_closed_at": session.check_in_closed_at.isoformat() if session.check_in_closed_at else None,
        "check_in_duration_minutes": session.check_in_duration_minutes or 30,
        "checked_in_count": checked_in,
        "has_qr_token": bool((session.check_in_token or "").strip()) and session.student_check_in_open,
    }


QR_TOKEN_ROTATE_SECONDS = 30


def _issue_check_in_token(session: LectureAttendanceSession, *, force: bool = False) -> LectureAttendanceSession:
    """Create or rotate the QR token while check-in is open."""
    import secrets
    from datetime import timedelta

    from django.utils import timezone as dj_tz

    now = dj_tz.now()
    issued = session.check_in_token_issued_at
    needs_rotate = force or not (session.check_in_token or "").strip()
    if not needs_rotate and issued:
        needs_rotate = (now - issued) >= timedelta(seconds=QR_TOKEN_ROTATE_SECONDS)
    if not needs_rotate:
        return session

    session.check_in_token = secrets.token_urlsafe(24)
    session.check_in_token_issued_at = now
    session.save(update_fields=["check_in_token", "check_in_token_issued_at", "updated_at"])
    return session


def _qr_payload_for_session(session: LectureAttendanceSession) -> dict:
    """Payload encoded in the QR (students scan this)."""
    return {
        "v": 1,
        "type": "ndu_attendance",
        "session_id": session.id,
        "token": (session.check_in_token or "").strip(),
        "course_code": session.course_unit.code if session.course_unit_id else "",
        "session_date": session.session_date.isoformat() if session.session_date else "",
    }


def _serialize_session(session: LectureAttendanceSession, *, include_records: bool = False) -> dict:
    course_unit = session.course_unit
    payload = {
        "id": session.id,
        "course_unit_id": course_unit.id,
        "course_code": course_unit.code,
        "course_name": course_unit.name,
        "session_date": session.session_date.isoformat(),
        "venue_label": session.venue_label or "",
        "notes": session.notes or "",
        "timetable_session_id": session.timetable_session_id,
        "slot_start_time": (
            session.timetable_session.start_time.strftime("%H:%M")
            if session.timetable_session_id and session.timetable_session
            else None
        ),
        "slot_end_time": (
            session.timetable_session.end_time.strftime("%H:%M")
            if session.timetable_session_id and session.timetable_session
            else None
        ),
        "slot_session_type": (
            session.timetable_session.session_type
            if session.timetable_session_id and session.timetable_session
            else None
        ),
        "taken_by": (
            {
                "id": session.taken_by_id,
                "name": session.taken_by.get_full_name() or session.taken_by.username,
            }
            if session.taken_by_id
            else None
        ),
        "locked_at": session.locked_at.isoformat() if session.locked_at else None,
        "is_locked": bool(session.locked_at),
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "record_count": getattr(session, "record_count", session.records.count()),
        **_check_in_payload(session),
    }
    program_batch = _programme_batch(course_unit)
    if program_batch and program_batch.program_id:
        payload["program_name"] = program_batch.program.name
        payload["program_batch_id"] = program_batch.id
        payload["program_batch_name"] = program_batch.name
    if course_unit.semester_id:
        payload["semester_name"] = course_unit.semester.name
    if include_records:
        records = session.records.select_related("student").all()
        by_student = {r.student_id: r for r in records}
        students = []
        for student in _enrolled_students(course_unit):
            rec = by_student.get(student.id)
            status_code = rec.status if rec else ""
            students.append(
                {
                    "student_id": student.id,
                    "student_number": student.student_id,
                    "reg_no": student.reg_no or "",
                    "name": student.full_name,
                    "status": status_code,
                    "status_label": STATUS_LABELS.get(status_code, ""),
                    "remark": rec.remark if rec else "",
                    "marked_via": rec.marked_via if rec else "",
                    "checked_in_at": rec.checked_in_at.isoformat() if rec and rec.checked_in_at else None,
                }
            )
        payload["students"] = students
        payload["students_count"] = len(students)
    return payload


def _roster_payload(
    course_unit: CourseUnit,
    session_date,
    session: LectureAttendanceSession | None,
    *,
    timetable_session: TimetableSession | None = None,
):
    existing = {}
    if session is not None:
        existing = {
            r.student_id: r
            for r in session.records.select_related("student").all()
        }
    enrolled = list(_enrolled_students(course_unit))
    from .attendance_stats import course_unit_student_attendance_map, min_attendance_percent_to_sit_exam

    stats_map = course_unit_student_attendance_map(
        course_unit, [s.id for s in enrolled], as_of=session_date
    )
    students = []
    for student in enrolled:
        rec = existing.get(student.id)
        stats = stats_map.get(student.id) or {}
        students.append(
            {
                "student_id": student.id,
                "student_number": student.student_id,
                "reg_no": student.reg_no or "",
                "name": student.full_name,
                "status": rec.status if rec else "",
                "status_label": STATUS_LABELS.get(rec.status, "") if rec else "",
                "remark": rec.remark if rec else "",
                "marked_via": rec.marked_via if rec else "",
                "checked_in_at": rec.checked_in_at.isoformat() if rec and rec.checked_in_at else None,
                "attendance_percent": stats.get("attendance_percent"),
                "sessions_attended": stats.get("sessions_attended", 0),
                "sessions_taken": stats.get("sessions_taken", 0),
                "meets_attendance_threshold": stats.get("meets_threshold", True),
            }
        )
    matched = timetable_session
    if matched is None and session and session.timetable_session_id:
        matched = session.timetable_session
    if matched is None:
        matched = _match_timetable_session(course_unit, session_date)
    venue_label = ""
    if session and session.venue_label:
        venue_label = session.venue_label
    elif matched is not None:
        venue_label = session_location_label(matched)
    return {
        "course": _serialize_course_unit(course_unit),
        "session_date": session_date.isoformat(),
        "session": _serialize_session(session) if session else None,
        "venue_label": venue_label,
        "timetable_session_id": matched.id if matched else None,
        "timetable": {
            "id": matched.id,
            "start_time": matched.start_time.strftime("%H:%M"),
            "end_time": matched.end_time.strftime("%H:%M"),
            "location": session_location_label(matched),
            "session_type": matched.session_type,
        }
        if matched
        else None,
        "students": students,
        "students_count": len(students),
        "min_attendance_percent_to_sit_exam": min_attendance_percent_to_sit_exam(),
        "is_locked": bool(session and session.locked_at),
        "status_choices": [
            {"value": value, "label": label} for value, label in LectureAttendanceRecord.STATUS_CHOICES
        ],
        **_check_in_payload(session),
    }


def _save_session(
    user,
    course_unit: CourseUnit,
    data: dict,
    *,
    marked_via: str = LectureAttendanceRecord.SOURCE_LECTURER,
    timetable_slot: TimetableSession | None = None,
) -> LectureAttendanceSession:
    session_date = _parse_date(data.get("session_date") or data.get("date"))
    if timetable_slot is None:
        try:
            timetable_slot = _resolve_timetable_slot_id(data.get("timetable_session_id"))
        except ValueError as exc:
            # Lecturer flows may still pass an id that must exist.
            if data.get("timetable_session_id") not in (None, "", 0, "0"):
                raise
            timetable_slot = None
    if timetable_slot is not None:
        course_unit = timetable_slot.course_unit
        session_date = _meeting_date_for_slot(
            timetable_slot, preferred_date=session_date
        )
    if not session_date:
        raise ValueError("session_date is required (YYYY-MM-DD).")

    records_payload = data.get("records") or data.get("students") or []
    if not isinstance(records_payload, list):
        raise ValueError("records must be a list.")

    enrolled_ids = {
        s.id
        for s in _enrolled_students(course_unit)
    }
    cleaned_records = []
    clear_student_ids = set()
    for row in records_payload:
        try:
            student_id = int(row.get("student_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if student_id not in enrolled_ids:
            continue
        status_code = str(row.get("status") or "").strip().lower()
        # Empty status = lecturer cleared / unmarked this student.
        if not status_code:
            clear_student_ids.add(student_id)
            continue
        if status_code not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status for student {student_id}. "
                f"Use one of: {', '.join(sorted(VALID_STATUSES))}."
            )
        # Lecturer/admin save always owns the mark (overrides QR / self-check-in).
        cleaned_records.append(
            {
                "student_id": student_id,
                "status": status_code,
                "remark": str(row.get("remark") or "")[:255],
                "marked_via": marked_via,
            }
        )

    matched = timetable_slot or _match_timetable_session(course_unit, session_date)
    venue_label = str(data.get("venue_label") or "").strip()
    if not venue_label and matched is not None:
        venue_label = session_location_label(matched)
    notes = str(data.get("notes") or "").strip()

    with transaction.atomic():
        session, _created = _get_or_create_attendance_session(
            course_unit=course_unit,
            session_date=session_date,
            timetable_session=matched,
            defaults={
                "taken_by": user,
                "venue_label": venue_label,
                "notes": notes,
            },
        )
        if session.locked_at:
            raise ValueError("This attendance session is locked and cannot be edited.")

        session.venue_label = venue_label or session.venue_label
        session.notes = notes if "notes" in data else session.notes
        if matched and session.timetable_session_id != matched.id:
            session.timetable_session = matched
        session.taken_by = user
        session.save()

        existing = {
            r.student_id: r
            for r in LectureAttendanceRecord.objects.filter(attendance_session=session)
        }
        to_create = []
        to_update = []
        from django.utils import timezone as dj_tz

        now = dj_tz.now()
        for row in cleaned_records:
            sid = row["student_id"]
            rec = existing.get(sid)
            via = row["marked_via"]
            if rec is None:
                to_create.append(
                    LectureAttendanceRecord(
                        attendance_session=session,
                        student_id=sid,
                        status=row["status"],
                        remark=row["remark"],
                        marked_via=via,
                        checked_in_at=now
                        if row["status"]
                        in (
                            LectureAttendanceRecord.STATUS_PRESENT,
                            LectureAttendanceRecord.STATUS_LATE,
                        )
                        else None,
                    )
                )
            else:
                rec.status = row["status"]
                rec.remark = row["remark"]
                rec.marked_via = via
                if row["status"] in (
                    LectureAttendanceRecord.STATUS_PRESENT,
                    LectureAttendanceRecord.STATUS_LATE,
                    LectureAttendanceRecord.STATUS_EXCUSED,
                ):
                    if not rec.checked_in_at:
                        rec.checked_in_at = now
                else:
                    # Lecturer override to absent — drop self-check timestamp.
                    rec.checked_in_at = None
                to_update.append(rec)

        if to_create:
            LectureAttendanceRecord.objects.bulk_create(to_create)
        if to_update:
            LectureAttendanceRecord.objects.bulk_update(
                to_update, ["status", "remark", "marked_via", "checked_in_at", "updated_at"]
            )

        to_delete_ids = set(clear_student_ids) | (set(existing.keys()) - enrolled_ids)
        if to_delete_ids:
            LectureAttendanceRecord.objects.filter(
                attendance_session=session, student_id__in=to_delete_ids
            ).delete()

    session.refresh_from_db()
    return session


def _get_or_create_session_shell(
    user,
    course_unit: CourseUnit,
    session_date,
    *,
    venue_label: str = "",
    notes: str = "",
    timetable_session: TimetableSession | None = None,
):
    matched = timetable_session or _match_timetable_session(course_unit, session_date)
    if not venue_label and matched is not None:
        venue_label = session_location_label(matched)
    with transaction.atomic():
        session, _ = _get_or_create_attendance_session(
            course_unit=course_unit,
            session_date=session_date,
            timetable_session=matched,
            defaults={
                "taken_by": user,
                "venue_label": venue_label or "",
                "notes": notes or "",
            },
        )
    if session.locked_at:
        raise ValueError("This attendance session is locked.")
    changed = False
    if venue_label and session.venue_label != venue_label:
        session.venue_label = venue_label
        changed = True
    if matched and session.timetable_session_id != matched.id:
        session.timetable_session = matched
        changed = True
    if not session.taken_by_id:
        session.taken_by = user
        changed = True
    if changed:
        session.save()
    return session


def _open_check_in(session: LectureAttendanceSession, *, duration_minutes: int | None = None) -> LectureAttendanceSession:
    from datetime import timedelta

    if session.locked_at:
        raise ValueError("This attendance session is locked. Unlock it before opening registration.")

    minutes = duration_minutes if duration_minutes is not None else session.check_in_duration_minutes or 30
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        minutes = 30
    # Large classes (~120) need ~20–30 min; allow up to 180 min (class length).
    minutes = max(5, min(minutes, 180))
    now = dj_tz.now()
    session.check_in_opened_at = now
    session.check_in_closes_at = now + timedelta(minutes=minutes)
    session.check_in_closed_at = None
    session.check_in_duration_minutes = minutes
    session.save(
        update_fields=[
            "check_in_opened_at",
            "check_in_closes_at",
            "check_in_closed_at",
            "check_in_duration_minutes",
            "updated_at",
        ]
    )
    return _issue_check_in_token(session, force=True)


def _close_check_in(session: LectureAttendanceSession) -> LectureAttendanceSession:
    from django.utils import timezone as dj_tz

    now = dj_tz.now()
    session.check_in_closed_at = now
    if not session.check_in_closes_at or session.check_in_closes_at > now:
        session.check_in_closes_at = now
    session.check_in_token = ""
    session.check_in_token_issued_at = None
    session.save(
        update_fields=[
            "check_in_closed_at",
            "check_in_closes_at",
            "check_in_token",
            "check_in_token_issued_at",
            "updated_at",
        ]
    )
    return session


def _lock_session(session: LectureAttendanceSession) -> LectureAttendanceSession:
    """Finalize attendance: close QR registration and prevent further edits."""
    if session.student_check_in_open or session.check_in_opened_at:
        session = _close_check_in(session)
    if session.locked_at:
        return session
    session.locked_at = dj_tz.now()
    session.save(update_fields=["locked_at", "updated_at"])
    return session


def _unlock_session(session: LectureAttendanceSession) -> LectureAttendanceSession:
    if not session.locked_at:
        return session
    session.locked_at = None
    session.save(update_fields=["locked_at", "updated_at"])
    return session


def _resolve_session_for_lock(data_or_params) -> LectureAttendanceSession | None:
    session_id = data_or_params.get("session_id")
    if session_id:
        return (
            LectureAttendanceSession.objects.filter(pk=session_id)
            .select_related("course_unit")
            .first()
        )
    try:
        course_unit_id = int(data_or_params.get("course_unit_id") or 0)
    except (TypeError, ValueError):
        course_unit_id = 0
    session_date = _parse_date(data_or_params.get("session_date") or data_or_params.get("date"))
    if not course_unit_id or not session_date:
        return None
    course_unit = _get_course_unit(course_unit_id)
    if not course_unit:
        return None
    timetable_slot = None
    try:
        timetable_slot = _resolve_timetable_slot_id(data_or_params.get("timetable_session_id"))
    except ValueError:
        timetable_slot = None
    return _find_attendance_session(
        course_unit, session_date, timetable_session=timetable_slot
    )


def _reload_session(session: LectureAttendanceSession) -> LectureAttendanceSession:
    return (
        LectureAttendanceSession.objects.select_related(
            "course_unit",
            "taken_by",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
        )
        .annotate(record_count=Count("records"))
        .get(pk=session.pk)
    )


def _admin_missing_meetings(*, capture_date, user=None, faculty_ids=None, program_batch_id=None) -> list[dict]:
    """Timetable class meetings on capture_date with no attendance session yet."""
    today = dj_tz.localdate()
    slots = (
        TimetableSession.objects.filter(is_active=True, is_published=True)
        .select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "course_unit__semester__program_batch",
            "course_unit__semester__program_batch__program",
            "venue",
            "venue__campus",
        )
        .prefetch_related("course_unit__lecturers")
        .order_by("start_time", "course_unit__code")
    )
    cu_qs = CourseUnit.objects.filter(is_active=True)
    if user is not None:
        cu_qs = filter_course_units_for_user(cu_qs, user)
    elif faculty_ids is not None:
        if not faculty_ids:
            return []
        cu_qs = cu_qs.filter(
            Q(program_batch__program__faculty_id__in=faculty_ids)
            | Q(semester__program_batch__program__faculty_id__in=faculty_ids)
        )
    cu_qs = _filter_course_units_by_program_batch(cu_qs, program_batch_id)
    slots = list(slots.filter(course_unit_id__in=cu_qs.values_list("id", flat=True)))

    existing = {
        (s.course_unit_id, s.session_date.isoformat(), s.timetable_session_id or 0): s.id
        for s in LectureAttendanceSession.objects.filter(session_date=capture_date).only(
            "id", "course_unit_id", "session_date", "timetable_session_id"
        )
    }

    # Count published slots per course on this date (for legacy no-slot registers).
    slots_per_course: dict[int, int] = {}
    for slot in slots:
        if slot.session_date:
            if slot.session_date != capture_date:
                continue
        elif capture_date.weekday() + 1 != slot.day_of_week:
            continue
        slots_per_course[slot.course_unit_id] = slots_per_course.get(slot.course_unit_id, 0) + 1

    missing: list[dict] = []
    for slot in slots:
        dates: list = []
        if slot.session_date:
            if slot.session_date == capture_date:
                dates = [slot.session_date]
        else:
            if capture_date.weekday() + 1 != slot.day_of_week:
                continue
            semester = getattr(slot.course_unit, "semester", None)
            sem_start = getattr(semester, "start_date", None) if semester else None
            sem_end = getattr(semester, "end_date", None) if semester else None
            if sem_start and capture_date < sem_start:
                continue
            if sem_end and capture_date > sem_end:
                continue
            dates = [capture_date]

        for meeting_date in dates:
            if meeting_date.weekday() + 1 != slot.day_of_week:
                continue
            key = (slot.course_unit_id, meeting_date.isoformat(), slot.id)
            if key in existing:
                continue
            legacy_key = (slot.course_unit_id, meeting_date.isoformat(), 0)
            if legacy_key in existing and slots_per_course.get(slot.course_unit_id, 0) <= 1:
                continue
            program_batch = _programme_batch(slot.course_unit)
            program = program_batch.program if program_batch else None
            lecturers = [
                {"id": u.id, "name": u.get_full_name() or u.username}
                for u in slot.course_unit.lecturers.all()[:5]
            ]
            missing.append(
                {
                    "key": f"{slot.id}:{meeting_date.isoformat()}",
                    "timetable_session_id": slot.id,
                    "course_unit_id": slot.course_unit_id,
                    "course_code": slot.course_unit.code,
                    "course_name": slot.course_unit.name,
                    "session_date": meeting_date.isoformat(),
                    "day_label": dict(TimetableSession.DAY_CHOICES).get(slot.day_of_week, ""),
                    "start_time": slot.start_time.strftime("%H:%M"),
                    "end_time": slot.end_time.strftime("%H:%M"),
                    "location": session_location_label(slot),
                    "session_type": slot.session_type,
                    "program_name": program.name if program else "",
                    "program_batch_id": program_batch.id if program_batch else None,
                    "program_batch_name": program_batch.name if program_batch else "",
                    "lecturers": lecturers,
                    "is_today": meeting_date == today,
                    "is_past": meeting_date < today,
                }
            )

    missing.sort(key=lambda m: (m["start_time"], m["course_code"]))
    return missing


def _pdf_response(session: LectureAttendanceSession, *, blank_sheet: bool = False) -> HttpResponse:
    course_unit = session.course_unit
    program_batch = _programme_batch(course_unit)
    program_name = ""
    semester_name = course_unit.semester.name if course_unit.semester_id else ""
    if program_batch and program_batch.program_id:
        program_name = program_batch.program.name

    records = {r.student_id: r for r in session.records.select_related("student")}
    students = []
    for student in _enrolled_students(course_unit):
        rec = records.get(student.id)
        students.append(
            {
                "reg_no": student.reg_no or student.student_id or "",
                "name": student.full_name,
                "status": rec.status if rec else "absent",
                "status_label": STATUS_LABELS.get(rec.status, "") if rec else "",
                "remark": rec.remark if rec else "",
            }
        )

    context = build_attendance_sheet_context(
        course_code=course_unit.code,
        course_name=course_unit.name,
        session_date_label=session.session_date.strftime("%d %B %Y"),
        programme_name=program_name,
        semester_name=semester_name,
        venue_label=session.venue_label,
        taken_by_name=(
            session.taken_by.get_full_name() or session.taken_by.username
            if session.taken_by_id
            else ""
        ),
        students=students,
        blank_sheet=blank_sheet,
    )
    pdf_bytes = render_attendance_sheet_pdf(context)
    filename = safe_attendance_pdf_filename(course_unit.code, session.session_date)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _blank_pdf_for_course(course_unit: CourseUnit, session_date, venue_label: str = "") -> HttpResponse:
    program_batch = _programme_batch(course_unit)
    program_name = ""
    semester_name = course_unit.semester.name if course_unit.semester_id else ""
    if program_batch and program_batch.program_id:
        program_name = program_batch.program.name
    matched = _match_timetable_session(course_unit, session_date)
    if not venue_label and matched is not None:
        venue_label = session_location_label(matched)
    students = [
        {
            "reg_no": s.reg_no or s.student_id or "",
            "name": s.full_name,
            "status": "",
            "status_label": "",
            "remark": "",
        }
        for s in _enrolled_students(course_unit)
    ]
    context = build_attendance_sheet_context(
        course_code=course_unit.code,
        course_name=course_unit.name,
        session_date_label=session_date.strftime("%d %B %Y"),
        programme_name=program_name,
        semester_name=semester_name,
        venue_label=venue_label,
        taken_by_name="",
        students=students,
        blank_sheet=True,
    )
    pdf_bytes = render_attendance_sheet_pdf(context)
    filename = safe_attendance_pdf_filename(course_unit.code, session_date)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class LecturerAttendanceCoursesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        courses = (
            request.user.course_units.filter(is_active=True)
            .select_related(
                "semester",
                "semester__program_batch",
                "program_batch",
                "program_batch__program",
                "program_batch__program__faculty",
            )
            .prefetch_related("lecturers")
            .order_by("code", "name")
        )
        return Response(
            {
                "lecturer_name": request.user.get_full_name(),
                "courses": [_serialize_course_unit(cu) for cu in courses],
            }
        )


class LecturerAttendanceScheduleView(APIView):
    """List timetable class meetings the lecturer can take attendance for (default: today)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        assigned_ids = _lecturer_assigned_course_unit_ids(request.user)
        today = dj_tz.localdate()
        if not assigned_ids:
            return Response(
                {
                    "today": today.isoformat(),
                    "date": today.isoformat(),
                    "from": None,
                    "to": None,
                    "meetings": [],
                    "meetings_count": 0,
                    "courses": [],
                    "assigned_course_unit_ids": [],
                    "detail": (
                        "No courses are assigned to you. "
                        "Ask an admin to assign you as lecturer on the course unit."
                    ),
                }
            )

        # Prefer a single capture date (today by default).
        capture_date = _parse_date(
            request.query_params.get("date")
            or request.query_params.get("session_date")
        ) or today
        from_date = _parse_date(request.query_params.get("from") or request.query_params.get("date_from"))
        to_date = _parse_date(request.query_params.get("to") or request.query_params.get("date_to"))
        if from_date is None and to_date is None:
            from_date = capture_date
            to_date = capture_date

        meetings = _lecturer_schedule_meetings(
            request.user, from_date=from_date, to_date=to_date
        )
        meeting_course_ids = {m["course_unit_id"] for m in meetings}

        # Course dropdown: only courses that have a class on the selected day.
        day_courses = (
            CourseUnit.objects.filter(id__in=meeting_course_ids, is_active=True)
            .select_related(
                "semester",
                "program_batch",
                "program_batch__program",
                "program_batch__program__faculty",
            )
            .prefetch_related("lecturers")
            .order_by("code", "name")
        )

        day_name = dict(TimetableSession.DAY_CHOICES).get(capture_date.weekday() + 1, "")
        return Response(
            {
                "today": today.isoformat(),
                "date": capture_date.isoformat(),
                "day_label": day_name,
                "from": from_date.isoformat() if from_date else capture_date.isoformat(),
                "to": to_date.isoformat() if to_date else capture_date.isoformat(),
                "meetings": meetings,
                "meetings_count": len(meetings),
                "assigned_course_unit_ids": assigned_ids,
                "courses": [_serialize_course_unit(cu) for cu in day_courses],
            }
        )


class LecturerAttendanceRosterView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        timetable_slot = None
        try:
            timetable_slot = _resolve_timetable_from_request(request.user, request.query_params)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        if timetable_slot:
            course_unit = timetable_slot.course_unit
            preferred = _parse_date(
                request.query_params.get("date") or request.query_params.get("session_date")
            )
            try:
                session_date = _meeting_date_for_slot(timetable_slot, preferred_date=preferred)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
        else:
            try:
                course_unit_id = int(request.query_params.get("course_unit_id") or 0)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Select a class from your timetable (timetable_session_id)."},
                    status=400,
                )
            session_date = _parse_date(
                request.query_params.get("date") or request.query_params.get("session_date")
            )
            if not course_unit_id or not session_date:
                return Response(
                    {
                        "detail": (
                            "Pick a scheduled class from your timetable, "
                            "or pass course_unit_id and date."
                        )
                    },
                    status=400,
                )
            course_unit = _get_course_unit(course_unit_id)
            if not course_unit:
                return Response({"detail": "Course unit not found."}, status=404)
            _assert_lecturer_course_access(request.user, course_unit)

        session = _find_attendance_session(
            course_unit, session_date, timetable_session=timetable_slot
        )
        return Response(
            _roster_payload(
                course_unit,
                session_date,
                session,
                timetable_session=timetable_slot,
            )
        )


class LecturerAttendanceSaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        timetable_slot = None
        try:
            timetable_slot = _resolve_timetable_from_request(request.user, request.data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        if timetable_slot:
            course_unit = timetable_slot.course_unit
            _assert_lecturer_course_access(request.user, course_unit)
        else:
            try:
                course_unit_id = int(request.data.get("course_unit_id") or 0)
            except (TypeError, ValueError):
                return Response({"detail": "course_unit_id is required."}, status=400)
            course_unit = _get_course_unit(course_unit_id)
            if not course_unit:
                return Response({"detail": "Course unit not found."}, status=404)
            _assert_lecturer_course_access(request.user, course_unit)

        via = LectureAttendanceRecord.SOURCE_PAPER
        if str(request.data.get("from_paper") or "").lower() not in ("1", "true", "yes"):
            via = LectureAttendanceRecord.SOURCE_LECTURER
        try:
            # Resolve date early so we can block future marking.
            preview_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
            if timetable_slot:
                preview_date = _meeting_date_for_slot(
                    timetable_slot, preferred_date=preview_date
                )
            if preview_date and preview_date > dj_tz.localdate():
                return Response(
                    {
                        "detail": (
                            "This lecture has not started yet. "
                            "Attendance can only be marked on the class day."
                        ),
                        "lecture_not_started": True,
                    },
                    status=400,
                )
            session = _save_session(
                request.user,
                course_unit,
                request.data,
                marked_via=via,
                timetable_slot=timetable_slot,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit", "taken_by", "timetable_session", "course_unit__semester",
                "course_unit__program_batch", "course_unit__program_batch__program",
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        return Response(_serialize_session(session, include_records=True))


class LecturerAttendanceOpenCheckInView(APIView):
    """Open student self-check-in window (default 30 minutes, max 180)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        timetable_slot = None
        try:
            timetable_slot = _resolve_timetable_from_request(request.user, request.data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        if timetable_slot:
            course_unit = timetable_slot.course_unit
            preferred = _parse_date(request.data.get("session_date") or request.data.get("date"))
            try:
                session_date = _meeting_date_for_slot(timetable_slot, preferred_date=preferred)
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=400)
        else:
            try:
                course_unit_id = int(request.data.get("course_unit_id") or 0)
            except (TypeError, ValueError):
                return Response({"detail": "course_unit_id is required."}, status=400)
            session_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
            if not course_unit_id or not session_date:
                return Response(
                    {"detail": "Pick a scheduled class from your timetable."},
                    status=400,
                )
            course_unit = _get_course_unit(course_unit_id)
            if not course_unit:
                return Response({"detail": "Course unit not found."}, status=404)
            _assert_lecturer_course_access(request.user, course_unit)

        today = dj_tz.localdate()
        if session_date < today:
            return Response(
                {
                    "detail": (
                        "Student registration is closed for past class dates. "
                        "Mark the roster manually instead."
                    ),
                    "registration_closed": True,
                },
                status=400,
            )
        if session_date > today:
            return Response(
                {
                    "detail": (
                        "This lecture has not started yet. "
                        "Open student registration on the class day."
                    ),
                    "lecture_not_started": True,
                },
                status=400,
            )

        try:
            session = _get_or_create_session_shell(
                request.user,
                course_unit,
                session_date,
                venue_label=str(request.data.get("venue_label") or ""),
                notes=str(request.data.get("notes") or ""),
                timetable_session=timetable_slot,
            )
            duration = request.data.get("duration_minutes")
            session = _open_check_in(
                session,
                duration_minutes=int(duration) if duration is not None else None,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit", "taken_by", "course_unit__semester",
                "course_unit__program_batch", "course_unit__program_batch__program",
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        return Response(_serialize_session(session, include_records=True))


class LecturerAttendanceCheckInQrView(APIView):
    """Return / rotate the QR payload for an open check-in window (projector display)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_id = request.query_params.get("session_id")
        course_unit_id = request.query_params.get("course_unit_id")
        session_date = _parse_date(request.query_params.get("session_date") or request.query_params.get("date"))
        session = None
        if session_id:
            session = (
                LectureAttendanceSession.objects.filter(pk=session_id)
                .select_related("course_unit")
                .first()
            )
        elif course_unit_id and session_date:
            try:
                slot = _resolve_timetable_slot_id(request.query_params.get("timetable_session_id"))
            except ValueError:
                slot = None
            cu = _get_course_unit(int(course_unit_id))
            session = (
                _find_attendance_session(cu, session_date, timetable_session=slot)
                if cu
                else None
            )
        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        _assert_lecturer_course_access(request.user, session.course_unit)
        if not session.student_check_in_open:
            return Response(
                {
                    "detail": "Student check-in is not open. Open registration first.",
                    "check_in_open": False,
                },
                status=400,
            )
        session = _issue_check_in_token(session)
        payload = _qr_payload_for_session(session)
        import json

        return Response(
            {
                "session_id": session.id,
                "course_code": session.course_unit.code,
                "course_name": session.course_unit.name,
                "session_date": session.session_date.isoformat(),
                "check_in_open": True,
                "check_in_closes_at": session.check_in_closes_at.isoformat()
                if session.check_in_closes_at
                else None,
                "checked_in_count": session.records.filter(
                    status__in=[
                        LectureAttendanceRecord.STATUS_PRESENT,
                        LectureAttendanceRecord.STATUS_LATE,
                        LectureAttendanceRecord.STATUS_EXCUSED,
                    ]
                ).count(),
                "token": session.check_in_token,
                "token_issued_at": session.check_in_token_issued_at.isoformat()
                if session.check_in_token_issued_at
                else None,
                "rotate_seconds": QR_TOKEN_ROTATE_SECONDS,
                "qr_payload": json.dumps(payload, separators=(",", ":")),
                "qr_data": payload,
            }
        )


class LecturerAttendanceCloseCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session_id = request.data.get("session_id")
        course_unit_id = request.data.get("course_unit_id")
        session_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
        session = None
        if session_id:
            session = LectureAttendanceSession.objects.filter(pk=session_id).select_related("course_unit").first()
        elif course_unit_id and session_date:
            try:
                slot = _resolve_timetable_slot_id(request.data.get("timetable_session_id"))
            except ValueError:
                slot = None
            try:
                cu = _get_course_unit(int(course_unit_id))
            except (TypeError, ValueError):
                cu = None
            session = (
                _find_attendance_session(cu, session_date, timetable_session=slot)
                if cu
                else None
            )
        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        _assert_lecturer_course_access(request.user, session.course_unit)
        session = _close_check_in(session)
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit", "taken_by", "course_unit__semester",
                "course_unit__program_batch", "course_unit__program_batch__program",
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        return Response(_serialize_session(session, include_records=True))


class LecturerAttendanceSessionPdfView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id: int):
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
                "taken_by",
            )
            .filter(pk=session_id)
            .first()
        )
        # placeholder — real method body continues below in file
        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        _assert_lecturer_course_access(request.user, session.course_unit)
        blank = str(request.query_params.get("blank") or "").lower() in ("1", "true", "yes")
        try:
            return _pdf_response(session, blank_sheet=blank)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)


class LecturerAttendanceBlankPdfView(APIView):
    """Generate a blank sign-in sheet before marks are saved."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            course_unit_id = int(request.query_params.get("course_unit_id") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "course_unit_id is required."}, status=400)
        session_date = _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
        if not course_unit_id or not session_date:
            return Response(
                {"detail": "course_unit_id and date (YYYY-MM-DD) are required."},
                status=400,
            )
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_lecturer_course_access(request.user, course_unit)
        try:
            return _blank_pdf_for_course(
                course_unit,
                session_date,
                venue_label=str(request.query_params.get("venue_label") or ""),
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)


class AdminAttendanceCoursesView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        qs = filter_course_units_for_user(_course_unit_qs().filter(is_active=True), request.user)
        program_id = _parse_int(request.query_params.get("program_id"))
        program_batch_id = _parse_int(
            request.query_params.get("program_batch_id")
            or request.query_params.get("batch_id")
        )
        semester_id = _parse_int(request.query_params.get("semester_id"))
        search = (request.query_params.get("search") or "").strip()
        if program_id:
            qs = qs.filter(
                Q(program_batch__program_id=program_id)
                | Q(semester__program_batch__program_id=program_id)
            )
        qs = _filter_course_units_by_program_batch(qs, program_batch_id)
        if semester_id:
            qs = qs.filter(semester_id=semester_id)
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        qs = qs.order_by("code", "name")[:300]
        return Response({"courses": [_serialize_course_unit(cu) for cu in qs]})


class AdminAttendanceBatchesView(APIView):
    """Programme batches in the caller's faculty/admin attendance scope."""

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        from admissions.faculty_scope import filter_program_batches_for_user

        from .models import ProgramBatch

        _assert_attendance_admin_write(request.user)
        qs = filter_program_batches_for_user(
            ProgramBatch.objects.filter(is_active=True).select_related("program"),
            request.user,
        ).order_by("program__name", "name", "id")
        batches = [
            {
                "id": b.id,
                "name": b.name,
                "academic_year": b.academic_year or "",
                "program_id": b.program_id,
                "program_name": b.program.name if b.program_id else "",
            }
            for b in qs[:500]
        ]
        return Response({"batches": batches, "count": len(batches)})


class AdminAttendanceSessionsView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        qs = filter_lecture_attendance_sessions_for_user(
            LectureAttendanceSession.objects.select_related(
                "course_unit",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
                "timetable_session",
                "taken_by",
            ).annotate(record_count=Count("records")),
            request.user,
        )

        course_unit_id = request.query_params.get("course_unit_id")
        program_id = _parse_int(request.query_params.get("program_id"))
        program_batch_id = _parse_int(
            request.query_params.get("program_batch_id")
            or request.query_params.get("batch_id")
        )
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        if course_unit_id:
            qs = qs.filter(course_unit_id=course_unit_id)
        if program_id:
            qs = qs.filter(
                Q(course_unit__program_batch__program_id=program_id)
                | Q(course_unit__semester__program_batch__program_id=program_id)
            )
        qs = _filter_sessions_by_program_batch(qs, program_batch_id)
        if date_from:
            qs = qs.filter(session_date__gte=date_from)
        if date_to:
            qs = qs.filter(session_date__lte=date_to)

        sessions = [_serialize_session(s) for s in qs.order_by("-session_date", "-id")[:200]]
        return Response({"sessions": sessions, "count": len(sessions)})


class AdminAttendanceRosterView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        try:
            course_unit_id = int(request.query_params.get("course_unit_id") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "course_unit_id is required."}, status=400)
        session_date = _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
        if not course_unit_id or not session_date:
            return Response(
                {"detail": "course_unit_id and date (YYYY-MM-DD) are required."},
                status=400,
            )
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)
        timetable_slot = None
        try:
            timetable_slot = _resolve_timetable_slot_id(
                request.query_params.get("timetable_session_id")
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        session = _find_attendance_session(
            course_unit, session_date, timetable_session=timetable_slot
        )
        return Response(
            _roster_payload(
                course_unit,
                session_date,
                session,
                timetable_session=timetable_slot,
            )
        )


class AdminAttendanceSaveView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def post(self, request):
        _assert_attendance_admin_write(request.user)
        try:
            course_unit_id = int(request.data.get("course_unit_id") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "course_unit_id is required."}, status=400)
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)
        timetable_slot = None
        try:
            timetable_slot = _resolve_timetable_slot_id(request.data.get("timetable_session_id"))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        try:
            session = _save_session(
                request.user,
                course_unit,
                request.data,
                marked_via=LectureAttendanceRecord.SOURCE_ADMIN,
                timetable_slot=timetable_slot,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit", "taken_by", "timetable_session", "course_unit__semester",
                "course_unit__program_batch", "course_unit__program_batch__program",
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        return Response(_serialize_session(session, include_records=True))


class AdminAttendanceSessionPdfView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request, session_id: int):
        _assert_attendance_admin_write(request.user)
        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
                "taken_by",
            )
            .filter(pk=session_id)
            .first()
        )
        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        _assert_admin_course_access(request.user, session.course_unit)
        blank = str(request.query_params.get("blank") or "").lower() in ("1", "true", "yes")
        try:
            return _pdf_response(session, blank_sheet=blank)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)


class AdminAttendanceBlankPdfView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        try:
            course_unit_id = int(request.query_params.get("course_unit_id") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "course_unit_id is required."}, status=400)
        session_date = _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
        if not course_unit_id or not session_date:
            return Response(
                {"detail": "course_unit_id and date (YYYY-MM-DD) are required."},
                status=400,
            )
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)
        try:
            return _blank_pdf_for_course(
                course_unit,
                session_date,
                venue_label=str(request.query_params.get("venue_label") or ""),
            )
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=500)


class StudentAttendanceOpenSessionsView(APIView):
    """List open / recent check-in sessions for the logged-in student."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from datetime import timedelta

        from payments.student_portal_finance import get_admitted_student_for_user

        admitted = get_admitted_student_for_user(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        enrolled_cu_ids = list(
            StudentCourseUnitEnrollment.objects.filter(
                student=admitted, status="enrolled"
            ).values_list("course_unit_id", flat=True)
        )
        if not enrolled_cu_ids:
            return Response({"sessions": [], "history": []})

        today = timezone_today()
        open_qs = (
            LectureAttendanceSession.objects.filter(
                course_unit_id__in=enrolled_cu_ids,
                session_date__gte=today - timedelta(days=1),
                session_date__lte=today,
                check_in_opened_at__isnull=False,
            )
            .select_related(
                "course_unit",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
            )
            .order_by("-session_date", "course_unit__code")
        )
        sessions_out = []
        for session in open_qs:
            rec = LectureAttendanceRecord.objects.filter(
                attendance_session=session, student=admitted
            ).first()
            already = bool(
                rec
                and rec.status
                in (
                    LectureAttendanceRecord.STATUS_PRESENT,
                    LectureAttendanceRecord.STATUS_LATE,
                    LectureAttendanceRecord.STATUS_EXCUSED,
                )
            )
            sessions_out.append(
                {
                    **_serialize_session(session),
                    "my_status": rec.status if rec else "",
                    "my_status_label": STATUS_LABELS.get(rec.status, "") if rec else "",
                    "can_self_check_in": session.student_check_in_open and not already,
                }
            )

        history = []
        hist_qs = list(
            LectureAttendanceSession.objects.filter(course_unit_id__in=enrolled_cu_ids)
            .select_related("course_unit")
            .order_by("-session_date", "-id")[:40]
        )
        records = {
            r.attendance_session_id: r
            for r in LectureAttendanceRecord.objects.filter(
                attendance_session_id__in=[s.id for s in hist_qs],
                student=admitted,
            )
        }
        for session in hist_qs:
            rec = records.get(session.id)
            history.append(
                {
                    "id": session.id,
                    "course_code": session.course_unit.code,
                    "course_name": session.course_unit.name,
                    "session_date": session.session_date.isoformat(),
                    "status": rec.status if rec else "",
                    "status_label": STATUS_LABELS.get(rec.status, "Not marked")
                    if rec
                    else "Not marked",
                    "check_in_open": session.student_check_in_open,
                }
            )

        return Response({"sessions": sessions_out, "history": history})


class StudentAttendanceSummaryView(APIView):
    """Per-course attendance % for the logged-in student (exam sit threshold)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from payments.student_portal_finance import get_admitted_student_for_user
        from .attendance_stats import min_attendance_percent_to_sit_exam, student_attendance_summaries

        admitted = get_admitted_student_for_user(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        as_of = _parse_date(request.query_params.get("as_of")) or dj_tz.localdate()
        summaries = student_attendance_summaries(admitted, as_of=as_of)
        return Response(
            {
                "as_of": as_of.isoformat(),
                "min_percent_required": min_attendance_percent_to_sit_exam(),
                "courses": summaries,
                "courses_count": len(summaries),
                "below_threshold_count": sum(
                    1 for s in summaries if s.get("sessions_taken") and not s.get("meets_threshold")
                ),
            }
        )


class LecturerAttendanceLockView(APIView):
    """Finalize (lock) or unlock a lecture attendance session."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        action = str(request.data.get("action") or "lock").strip().lower()
        session = _resolve_session_for_lock(request.data)
        if not session:
            # Allow lock to create shell only when locking after save — require existing session.
            return Response(
                {
                    "detail": (
                        "Attendance session not found. Save the roster first, then lock/finalize."
                    )
                },
                status=404,
            )
        _assert_lecturer_course_access(request.user, session.course_unit)

        try:
            if action in ("unlock", "reopen"):
                session = _unlock_session(session)
            else:
                session = _lock_session(session)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(_serialize_session(_reload_session(session), include_records=True))


class AdminAttendanceLockView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def post(self, request):
        _assert_attendance_admin_write(request.user)
        action = str(request.data.get("action") or "lock").strip().lower()
        session = _resolve_session_for_lock(request.data)
        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        _assert_admin_course_access(request.user, session.course_unit)

        try:
            if action in ("unlock", "reopen"):
                session = _unlock_session(session)
            else:
                session = _lock_session(session)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(_serialize_session(_reload_session(session), include_records=True))


class AdminAttendanceMissingView(APIView):
    """
    Missing-roll queue: published timetable meetings on a date with no attendance session.
    Admins can open the roster and take attendance on behalf of the lecturer.
    """

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        today = dj_tz.localdate()
        capture_date = (
            _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
            or today
        )
        faculty_ids = user_faculty_ids(request.user)
        program_batch_id = _parse_int(
            request.query_params.get("program_batch_id")
            or request.query_params.get("batch_id")
        )
        missing = _admin_missing_meetings(
            capture_date=capture_date,
            user=request.user,
            faculty_ids=faculty_ids,
            program_batch_id=program_batch_id,
        )
        day_name = dict(TimetableSession.DAY_CHOICES).get(capture_date.weekday() + 1, "")
        return Response(
            {
                "today": today.isoformat(),
                "date": capture_date.isoformat(),
                "day_label": day_name,
                "missing": missing,
                "missing_count": len(missing),
            }
        )


class StudentAttendanceCheckInView(APIView):
    """Student marks themselves present while the lecturer window is open."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django.utils import timezone as dj_tz
        from payments.student_portal_finance import get_admitted_student_for_user

        admitted = get_admitted_student_for_user(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        session_id = request.data.get("session_id")
        session = None
        if session_id:
            session = (
                LectureAttendanceSession.objects.select_related("course_unit")
                .filter(pk=session_id)
                .first()
            )
        else:
            try:
                course_unit_id = int(request.data.get("course_unit_id") or 0)
            except (TypeError, ValueError):
                course_unit_id = 0
            session_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
            if course_unit_id and session_date:
                session = (
                    LectureAttendanceSession.objects.filter(
                        course_unit_id=course_unit_id, session_date=session_date
                    )
                    .select_related("course_unit")
                    .first()
                )

        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)

        enrolled = StudentCourseUnitEnrollment.objects.filter(
            student=admitted, course_unit=session.course_unit, status="enrolled"
        ).exists()
        if not enrolled:
            return Response({"detail": "You are not enrolled in this course."}, status=403)

        if not session.student_check_in_open:
            return Response(
                {
                    "detail": (
                        "Self-check-in is closed. If you attended, ask the lecturer "
                        "to mark you present (or sign the paper register)."
                    )
                },
                status=400,
            )

        token = str(request.data.get("token") or "").strip()
        if not token:
            return Response(
                {
                    "detail": (
                        "Scan the lecturer's QR code to check in. "
                        "If you do not have a smartphone, go to the lecturer to be marked present."
                    )
                },
                status=400,
            )
        current = (session.check_in_token or "").strip()
        if not current or token != current:
            return Response(
                {
                    "detail": (
                        "This QR code is expired or invalid. Ask the lecturer to show "
                        "the current code on the screen. Without a phone, go to the lecturer."
                    )
                },
                status=400,
            )

        now = dj_tz.now()
        marked_via = LectureAttendanceRecord.SOURCE_QR
        remark = "QR scan check-in"
        rec, created = LectureAttendanceRecord.objects.get_or_create(
            attendance_session=session,
            student=admitted,
            defaults={
                "status": LectureAttendanceRecord.STATUS_PRESENT,
                "marked_via": marked_via,
                "checked_in_at": now,
                "remark": remark,
            },
        )
        if not created:
            # Lecturer / admin / paper marks win — student cannot override.
            if rec.marked_via in (
                LectureAttendanceRecord.SOURCE_LECTURER,
                LectureAttendanceRecord.SOURCE_ADMIN,
                LectureAttendanceRecord.SOURCE_PAPER,
            ):
                return Response(
                    {
                        "detail": (
                            "Your lecturer already set your attendance for this class. "
                            "Ask them if it needs changing."
                        ),
                        "status": rec.status,
                        "status_label": STATUS_LABELS.get(rec.status, ""),
                    },
                    status=400,
                )
            if rec.status in (
                LectureAttendanceRecord.STATUS_PRESENT,
                LectureAttendanceRecord.STATUS_LATE,
                LectureAttendanceRecord.STATUS_EXCUSED,
            ):
                return Response(
                    {
                        "detail": "You are already marked for this class.",
                        "status": rec.status,
                        "status_label": STATUS_LABELS.get(rec.status, ""),
                    }
                )
            rec.status = LectureAttendanceRecord.STATUS_PRESENT
            rec.marked_via = marked_via
            rec.checked_in_at = now
            if not rec.remark:
                rec.remark = remark
            rec.save(
                update_fields=["status", "marked_via", "checked_in_at", "remark", "updated_at"]
            )

        return Response(
            {
                "detail": "Attendance recorded. You are marked present.",
                "session_id": session.id,
                "status": LectureAttendanceRecord.STATUS_PRESENT,
                "status_label": "Present",
                "checked_in_at": now.isoformat(),
                "checked_in_count": session.records.filter(
                    status__in=[
                        LectureAttendanceRecord.STATUS_PRESENT,
                        LectureAttendanceRecord.STATUS_LATE,
                        LectureAttendanceRecord.STATUS_EXCUSED,
                    ]
                ).count(),
            }
        )


class AdminAttendanceReportView(APIView):
    """
    Faculty/admin attendance report: course averages + students below exam-sit %.
    Pass export=csv (or download=csv) for CSV download.
    Do not use format=csv — DRF reserves `format` for content negotiation.
    """

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        import csv
        import io

        from .attendance_stats import faculty_attendance_report

        _assert_attendance_admin_write(request.user)
        qs = filter_course_units_for_user(_course_unit_qs().filter(is_active=True), request.user)
        program_batch_id = _parse_int(
            request.query_params.get("program_batch_id")
            or request.query_params.get("batch_id")
        )
        program_id = _parse_int(request.query_params.get("program_id"))
        course_unit_id = _parse_int(request.query_params.get("course_unit_id"))
        as_of = _parse_date(request.query_params.get("as_of")) or dj_tz.localdate()
        qs = _filter_course_units_by_program_batch(qs, program_batch_id)
        if program_id:
            qs = qs.filter(
                Q(program_batch__program_id=program_id)
                | Q(semester__program_batch__program_id=program_id)
            )
        if course_unit_id:
            qs = qs.filter(pk=course_unit_id)
        qs = qs.order_by("code", "name")[:200]

        report = faculty_attendance_report(course_units=qs, as_of=as_of)
        fmt = str(
            request.query_params.get("export")
            or request.query_params.get("download")
            or ""
        ).strip().lower()
        if fmt == "csv":
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                [
                    "reg_no",
                    "student_number",
                    "name",
                    "course_code",
                    "course_name",
                    "sessions_attended",
                    "sessions_taken",
                    "attendance_percent",
                    "min_percent_required",
                    "as_of",
                ]
            )
            for row in report["below_threshold"]:
                writer.writerow(
                    [
                        row.get("reg_no") or "",
                        row.get("student_number") or "",
                        row.get("name") or "",
                        row.get("course_code") or "",
                        row.get("course_name") or "",
                        row.get("sessions_attended") or 0,
                        row.get("sessions_taken") or 0,
                        row.get("attendance_percent")
                        if row.get("attendance_percent") is not None
                        else "",
                        row.get("min_percent_required") or "",
                        report.get("as_of") or "",
                    ]
                )
            # Also append a course summary sheet section
            writer.writerow([])
            writer.writerow(["COURSE SUMMARY"])
            writer.writerow(
                [
                    "course_code",
                    "course_name",
                    "program_name",
                    "program_batch_name",
                    "students_enrolled",
                    "sessions_taken",
                    "average_attendance_percent",
                    "below_threshold_count",
                    "min_percent_required",
                ]
            )
            for c in report["courses"]:
                writer.writerow(
                    [
                        c.get("course_code") or "",
                        c.get("course_name") or "",
                        c.get("program_name") or "",
                        c.get("program_batch_name") or "",
                        c.get("students_enrolled") or 0,
                        c.get("sessions_taken") or 0,
                        c.get("average_attendance_percent")
                        if c.get("average_attendance_percent") is not None
                        else "",
                        c.get("below_threshold_count") or 0,
                        c.get("min_percent_required") or "",
                    ]
                )
            resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
            resp["Content-Disposition"] = (
                f'attachment; filename="attendance_report_{as_of.isoformat()}.csv"'
            )
            return resp

        return Response(report)


def timezone_today():
    from django.utils import timezone as dj_tz

    return dj_tz.localdate()
