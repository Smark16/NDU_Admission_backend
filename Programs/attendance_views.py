"""Lecture attendance APIs for lecturers and faculty/admins."""
from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.faculty_scope import user_faculty_ids

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
from .timetable_utils import session_location_label


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
    from rest_framework.exceptions import PermissionDenied
    from admissions.faculty_scope import assert_program_batch_access

    program_batch = _programme_batch(course_unit)
    if program_batch is None:
        raise PermissionDenied("Course unit is not linked to a programme batch.")
    assert_program_batch_access(user, program_batch)


def _assert_attendance_admin_write(user) -> None:
    from rest_framework.exceptions import PermissionDenied
    from accounts.super_admin import user_is_super_admin
    from accounts.erp_drf_permissions import user_has_any_erp_perm
    from admissions.faculty_scope import user_is_faculty_admin, user_is_faculty_dean

    if user_is_super_admin(user):
        return
    if user_is_faculty_admin(user) or user_is_faculty_dean(user):
        return
    if user_has_any_erp_perm(user, "access_academics", "manage_program_scheduling"):
        return
    if user.has_perm("Programs.manage_faculty_lecture_attendance"):
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


def _match_timetable_session(course_unit: CourseUnit, session_date):
    return (
        TimetableSession.objects.filter(
            course_unit=course_unit,
            is_active=True,
            is_published=True,
            session_date=session_date,
        )
        .select_related("venue", "venue__campus")
        .order_by("start_time")
        .first()
    )


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
        "taken_by": (
            {
                "id": session.taken_by_id,
                "name": session.taken_by.get_full_name() or session.taken_by.username,
            }
            if session.taken_by_id
            else None
        ),
        "locked_at": session.locked_at.isoformat() if session.locked_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
        "record_count": getattr(session, "record_count", session.records.count()),
        **_check_in_payload(session),
    }
    program_batch = _programme_batch(course_unit)
    if program_batch and program_batch.program_id:
        payload["program_name"] = program_batch.program.name
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


def _roster_payload(course_unit: CourseUnit, session_date, session: LectureAttendanceSession | None):
    existing = {}
    if session is not None:
        existing = {
            r.student_id: r
            for r in session.records.select_related("student").all()
        }
    students = []
    for student in _enrolled_students(course_unit):
        rec = existing.get(student.id)
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
            }
        )
    matched = None
    if session and session.timetable_session_id:
        matched = session.timetable_session
    else:
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
        "students": students,
        "students_count": len(students),
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
) -> LectureAttendanceSession:
    session_date = _parse_date(data.get("session_date"))
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
    for row in records_payload:
        try:
            student_id = int(row.get("student_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if student_id not in enrolled_ids:
            continue
        status_code = str(row.get("status") or "").strip().lower()
        if status_code not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status for student {student_id}. "
                f"Use one of: {', '.join(sorted(VALID_STATUSES))}."
            )
        row_via = str(row.get("marked_via") or marked_via).strip().lower() or marked_via
        cleaned_records.append(
            {
                "student_id": student_id,
                "status": status_code,
                "remark": str(row.get("remark") or "")[:255],
                "marked_via": row_via,
            }
        )

    matched = _match_timetable_session(course_unit, session_date)
    venue_label = str(data.get("venue_label") or "").strip()
    if not venue_label and matched is not None:
        venue_label = session_location_label(matched)
    notes = str(data.get("notes") or "").strip()

    with transaction.atomic():
        session, _created = LectureAttendanceSession.objects.select_for_update().get_or_create(
            course_unit=course_unit,
            session_date=session_date,
            defaults={
                "taken_by": user,
                "venue_label": venue_label,
                "notes": notes,
                "timetable_session": matched,
            },
        )
        if session.locked_at:
            raise ValueError("This attendance session is locked and cannot be edited.")

        session.venue_label = venue_label or session.venue_label
        session.notes = notes if "notes" in data else session.notes
        if matched and not session.timetable_session_id:
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
                ) and not rec.checked_in_at:
                    rec.checked_in_at = now
                to_update.append(rec)

        if to_create:
            LectureAttendanceRecord.objects.bulk_create(to_create)
        if to_update:
            LectureAttendanceRecord.objects.bulk_update(
                to_update, ["status", "remark", "marked_via", "checked_in_at", "updated_at"]
            )

        obsolete = set(existing.keys()) - enrolled_ids
        if obsolete:
            LectureAttendanceRecord.objects.filter(
                attendance_session=session, student_id__in=obsolete
            ).delete()

    session.refresh_from_db()
    return session


def _get_or_create_session_shell(user, course_unit: CourseUnit, session_date, *, venue_label: str = "", notes: str = ""):
    matched = _match_timetable_session(course_unit, session_date)
    if not venue_label and matched is not None:
        venue_label = session_location_label(matched)
    session, _ = LectureAttendanceSession.objects.get_or_create(
        course_unit=course_unit,
        session_date=session_date,
        defaults={
            "taken_by": user,
            "venue_label": venue_label or "",
            "notes": notes or "",
            "timetable_session": matched,
        },
    )
    if session.locked_at:
        raise ValueError("This attendance session is locked.")
    changed = False
    if venue_label and session.venue_label != venue_label:
        session.venue_label = venue_label
        changed = True
    if matched and not session.timetable_session_id:
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

    from django.utils import timezone as dj_tz

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
    return session


def _close_check_in(session: LectureAttendanceSession) -> LectureAttendanceSession:
    from django.utils import timezone as dj_tz

    now = dj_tz.now()
    session.check_in_closed_at = now
    if not session.check_in_closes_at or session.check_in_closes_at > now:
        session.check_in_closes_at = now
    session.save(update_fields=["check_in_closed_at", "check_in_closes_at", "updated_at"])
    return session


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


class LecturerAttendanceRosterView(APIView):
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
        session = (
            LectureAttendanceSession.objects.filter(
                course_unit=course_unit, session_date=session_date
            )
            .select_related("taken_by", "timetable_session", "course_unit")
            .first()
        )
        return Response(_roster_payload(course_unit, session_date, session))


class LecturerAttendanceSaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
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
            session = _save_session(request.user, course_unit, request.data, marked_via=via)
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
        try:
            course_unit_id = int(request.data.get("course_unit_id") or 0)
        except (TypeError, ValueError):
            return Response({"detail": "course_unit_id is required."}, status=400)
        session_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
        if not course_unit_id or not session_date:
            return Response(
                {"detail": "course_unit_id and session_date are required."},
                status=400,
            )
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_lecturer_course_access(request.user, course_unit)
        try:
            session = _get_or_create_session_shell(
                request.user,
                course_unit,
                session_date,
                venue_label=str(request.data.get("venue_label") or ""),
                notes=str(request.data.get("notes") or ""),
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
            session = LectureAttendanceSession.objects.filter(
                course_unit_id=course_unit_id, session_date=session_date
            ).select_related("course_unit").first()
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
        qs = _course_unit_qs().filter(is_active=True)
        faculty_ids = user_faculty_ids(request.user)
        if faculty_ids is not None:
            qs = qs.filter(
                Q(program_batch__program__faculty_id__in=faculty_ids)
                | Q(semester__program_batch__program__faculty_id__in=faculty_ids)
            )
        program_id = request.query_params.get("program_id")
        semester_id = request.query_params.get("semester_id")
        search = (request.query_params.get("search") or "").strip()
        if program_id:
            qs = qs.filter(
                Q(program_batch__program_id=program_id)
                | Q(semester__program_batch__program_id=program_id)
            )
        if semester_id:
            qs = qs.filter(semester_id=semester_id)
        if search:
            qs = qs.filter(Q(code__icontains=search) | Q(name__icontains=search))
        qs = qs.order_by("code", "name")[:300]
        return Response({"courses": [_serialize_course_unit(cu) for cu in qs]})


class AdminAttendanceSessionsView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        qs = LectureAttendanceSession.objects.select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "taken_by",
        ).annotate(record_count=Count("records"))

        faculty_ids = user_faculty_ids(request.user)
        if faculty_ids is not None:
            qs = qs.filter(
                Q(course_unit__program_batch__program__faculty_id__in=faculty_ids)
                | Q(course_unit__semester__program_batch__program__faculty_id__in=faculty_ids)
            )

        course_unit_id = request.query_params.get("course_unit_id")
        program_id = request.query_params.get("program_id")
        date_from = _parse_date(request.query_params.get("date_from"))
        date_to = _parse_date(request.query_params.get("date_to"))
        if course_unit_id:
            qs = qs.filter(course_unit_id=course_unit_id)
        if program_id:
            qs = qs.filter(
                Q(course_unit__program_batch__program_id=program_id)
                | Q(course_unit__semester__program_batch__program_id=program_id)
            )
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
        session = (
            LectureAttendanceSession.objects.filter(
                course_unit=course_unit, session_date=session_date
            )
            .select_related("taken_by", "timetable_session", "course_unit")
            .first()
        )
        return Response(_roster_payload(course_unit, session_date, session))


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
        try:
            session = _save_session(
                request.user,
                course_unit,
                request.data,
                marked_via=LectureAttendanceRecord.SOURCE_ADMIN,
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
                        "Self-check-in is closed. If you attended, sign the paper register "
                        "or ask the lecturer to mark you."
                    )
                },
                status=400,
            )

        now = dj_tz.now()
        rec, created = LectureAttendanceRecord.objects.get_or_create(
            attendance_session=session,
            student=admitted,
            defaults={
                "status": LectureAttendanceRecord.STATUS_PRESENT,
                "marked_via": LectureAttendanceRecord.SOURCE_STUDENT,
                "checked_in_at": now,
                "remark": "Self check-in",
            },
        )
        if not created:
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
            rec.marked_via = LectureAttendanceRecord.SOURCE_STUDENT
            rec.checked_in_at = now
            if not rec.remark:
                rec.remark = "Self check-in"
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


def timezone_today():
    from django.utils import timezone as dj_tz

    return dj_tz.localdate()
