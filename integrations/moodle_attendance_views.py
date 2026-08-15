"""Moodle / LMS attendance — same lecture registers as the portal."""
from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.attendance_stats import student_course_attendance_summary
from Programs.attendance_views import (
    WRITABLE_ATTENDANCE_STATUSES,
    _enrolled_students,
    _get_or_create_attendance_session,
    _match_timetable_session,
    _resolve_timetable_slot_id,
)
from Programs.models import (
    CourseUnit,
    LectureAttendanceRecord,
    LectureAttendanceSession,
    StudentCourseUnitEnrollment,
)

from .permissions import HasMoodleApiKey
from .services import log_moodle_access, resolve_student_by_lookup

LMS_STATUSES = WRITABLE_ATTENDANCE_STATUSES  # present | absent only (no late, excused, or QR)


def _lms_mark(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    if value in ("present", "late", "excused"):
        return LectureAttendanceRecord.STATUS_PRESENT
    if value == "absent":
        return LectureAttendanceRecord.STATUS_ABSENT
    return None


def _key_prefix(request) -> str:
    return getattr(request, "moodle_api_key_prefix", "") or ""


def _active_course_unit(course_unit_id: int) -> CourseUnit | None:
    return CourseUnit.objects.filter(pk=course_unit_id, is_active=True).first()


def _session_payload(session: LectureAttendanceSession) -> dict:
    cu = session.course_unit
    slot = session.timetable_session
    return {
        "id": session.id,
        "course_unit_id": cu.id,
        "course_code": cu.code,
        "course_name": cu.name,
        "session_date": session.session_date.isoformat(),
        "venue_label": session.venue_label or "",
        "notes": session.notes or "",
        "timetable_session_id": session.timetable_session_id,
        "slot_start_time": slot.start_time.strftime("%H:%M") if slot and slot.start_time else None,
        "slot_end_time": slot.end_time.strftime("%H:%M") if slot and slot.end_time else None,
        "locked_at": session.locked_at.isoformat() if session.locked_at else None,
        "is_locked": bool(session.locked_at),
        "record_count": getattr(session, "record_count", session.records.count()),
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


class MoodleAttendanceSessionsView(APIView):
    """List or open a lecture attendance session for a course unit."""

    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, course_unit_id: int):
        endpoint = "moodle/attendance/sessions"
        cu = _active_course_unit(course_unit_id)
        if not cu:
            log_moodle_access(endpoint=endpoint, http_status=404, key_prefix=_key_prefix(request))
            return Response({"ok": False, "detail": "Course unit not found."}, status=404)

        qs = LectureAttendanceSession.objects.filter(course_unit=cu).select_related(
            "course_unit", "timetable_session", "taken_by"
        )
        from_raw = (request.query_params.get("from") or "").strip()
        to_raw = (request.query_params.get("to") or "").strip()
        if from_raw:
            start = parse_date(from_raw)
            if start:
                qs = qs.filter(session_date__gte=start)
        if to_raw:
            end = parse_date(to_raw)
            if end:
                qs = qs.filter(session_date__lte=end)
        if not from_raw and not to_raw:
            qs = qs.filter(session_date__gte=dj_tz.localdate() - timedelta(days=90))

        rows = [
            _session_payload(s)
            for s in qs.annotate(record_count=Count("records")).order_by("-session_date", "-id")[:100]
        ]
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"cu={course_unit_id};count={len(rows)}",
        )
        return Response({"ok": True, "course_unit_id": cu.pk, "course_code": cu.code, "sessions": rows})

    def post(self, request, course_unit_id: int):
        endpoint = "moodle/attendance/sessions"
        cu = _active_course_unit(course_unit_id)
        if not cu:
            return Response({"ok": False, "detail": "Course unit not found."}, status=404)

        data = request.data if isinstance(request.data, dict) else {}
        session_date = parse_date(str(data.get("session_date") or data.get("date") or ""))
        if not session_date:
            return Response(
                {"ok": False, "detail": "session_date is required (YYYY-MM-DD)."},
                status=400,
            )
        try:
            slot = _resolve_timetable_slot_id(data.get("timetable_session_id"))
        except ValueError as exc:
            return Response({"ok": False, "detail": str(exc)}, status=400)
        if slot is not None and slot.course_unit_id != cu.pk:
            return Response(
                {"ok": False, "detail": "timetable_session_id does not belong to this course unit."},
                status=400,
            )
        matched = slot or _match_timetable_session(cu, session_date)
        venue = str(data.get("venue_label") or "").strip()
        notes = str(data.get("notes") or "").strip()

        with transaction.atomic():
            session, created = _get_or_create_attendance_session(
                course_unit=cu,
                session_date=session_date,
                timetable_session=matched,
                defaults={"venue_label": venue, "notes": notes},
            )
            if session.locked_at:
                return Response(
                    {"ok": False, "detail": "This attendance session is locked."},
                    status=409,
                )
            if venue:
                session.venue_label = venue
            if notes:
                session.notes = notes
            session.save()

        session = (
            LectureAttendanceSession.objects.select_related(
                "course_unit", "timetable_session", "taken_by"
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"cu={course_unit_id};session={session.pk};created={created}",
        )
        return Response(
            {"ok": True, "created": created, "session": _session_payload(session)},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MoodleAttendanceSessionDetailView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, session_id: int):
        endpoint = "moodle/attendance/session"
        session = (
            LectureAttendanceSession.objects.filter(pk=session_id)
            .select_related("course_unit", "timetable_session", "taken_by")
            .first()
        )
        if not session:
            return Response({"ok": False, "detail": "Attendance session not found."}, status=404)

        enrolled = _enrolled_students(session.course_unit)
        records = {
            r.student_id: r
            for r in session.records.select_related("student")
        }
        roster = []
        for st in enrolled:
            rec = records.get(st.pk)
            roster.append(
                {
                    "reg_no": st.reg_no or "",
                    "student_id": st.student_id or "",
                    "full_name": st.full_name or "",
                    "status": _lms_mark(rec.status) if rec else None,
                    "remark": rec.remark if rec else "",
                    "marked_via": rec.marked_via if rec else None,
                }
            )
        payload = _session_payload(session)
        payload["roster"] = roster
        payload["enrolled_count"] = len(roster)
        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"session={session_id}",
        )
        return Response({"ok": True, "session": payload})


class MoodleAttendanceRecordsView(APIView):
    """Upsert marks from Moodle / any LMS. Does not wipe students omitted from the payload."""

    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def post(self, request, session_id: int):
        endpoint = "moodle/attendance/records"
        session = (
            LectureAttendanceSession.objects.filter(pk=session_id)
            .select_related("course_unit")
            .first()
        )
        if not session:
            return Response({"ok": False, "detail": "Attendance session not found."}, status=404)
        if session.locked_at:
            return Response({"ok": False, "detail": "This attendance session is locked."}, status=409)

        data = request.data if isinstance(request.data, dict) else {}
        rows = data.get("records") or data.get("students") or []
        if not isinstance(rows, list) or not rows:
            return Response({"ok": False, "detail": "records must be a non-empty list."}, status=400)

        enrolled = {s.pk: s for s in _enrolled_students(session.course_unit)}
        now = dj_tz.now()
        saved = 0
        skipped = []

        with transaction.atomic():
            existing = {
                r.student_id: r
                for r in LectureAttendanceRecord.objects.select_for_update().filter(
                    attendance_session=session
                )
            }
            to_create = []
            to_update = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                lookup = (
                    (row.get("reg_no") or row.get("student_id") or row.get("username") or "")
                )
                lookup = str(lookup).strip()
                student = resolve_student_by_lookup(lookup) if lookup else None
                if student is None:
                    skipped.append({"lookup": lookup, "reason": "student_not_found"})
                    continue
                if student.pk not in enrolled:
                    skipped.append({"lookup": lookup, "reason": "not_enrolled"})
                    continue
                status_code = str(row.get("status") or "").strip().lower()
                if status_code not in LMS_STATUSES:
                    skipped.append(
                        {
                            "lookup": lookup,
                            "reason": "invalid_status",
                            "detail": "Use present or absent only.",
                        }
                    )
                    continue
                remark = str(row.get("remark") or "")[:255]
                rec = existing.get(student.pk)
                present = status_code == LectureAttendanceRecord.STATUS_PRESENT
                if rec is None:
                    to_create.append(
                        LectureAttendanceRecord(
                            attendance_session=session,
                            student_id=student.pk,
                            status=status_code,
                            remark=remark,
                            marked_via=LectureAttendanceRecord.SOURCE_LMS,
                            checked_in_at=now if present else None,
                        )
                    )
                else:
                    rec.status = status_code
                    rec.remark = remark
                    rec.marked_via = LectureAttendanceRecord.SOURCE_LMS
                    if present:
                        if not rec.checked_in_at:
                            rec.checked_in_at = now
                    else:
                        rec.checked_in_at = None
                    to_update.append(rec)
                saved += 1

            if to_create:
                LectureAttendanceRecord.objects.bulk_create(to_create)
            if to_update:
                LectureAttendanceRecord.objects.bulk_update(
                    to_update, ["status", "remark", "marked_via", "checked_in_at", "updated_at"]
                )

        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"session={session_id};saved={saved};skipped={len(skipped)}",
        )
        return Response(
            {
                "ok": True,
                "session_id": session.pk,
                "saved": saved,
                "skipped": skipped,
            }
        )


class MoodleStudentAttendanceView(APIView):
    authentication_classes = []
    permission_classes = [HasMoodleApiKey]

    def get(self, request, reg_no: str):
        endpoint = "moodle/student-attendance"
        student = resolve_student_by_lookup(reg_no)
        if not student:
            return Response({"ok": False, "detail": "Student not found."}, status=404)

        cu_raw = (request.query_params.get("course_unit_id") or "").strip()
        enrollments = StudentCourseUnitEnrollment.objects.filter(
            student=student, status="enrolled"
        ).select_related("course_unit")
        if cu_raw:
            try:
                enrollments = enrollments.filter(course_unit_id=int(cu_raw))
            except (TypeError, ValueError):
                return Response({"ok": False, "detail": "course_unit_id must be an integer."}, status=400)

        courses = []
        for enr in enrollments.select_related("course_unit")[:80]:
            if not enr.course_unit_id:
                continue
            courses.append(student_course_attendance_summary(student, enr.course_unit))

        log_moodle_access(
            endpoint=endpoint,
            http_status=200,
            key_prefix=_key_prefix(request),
            detail=f"{student.reg_no};courses={len(courses)}",
        )
        return Response(
            {
                "ok": True,
                "reg_no": student.reg_no or "",
                "student_id": student.student_id or "",
                "full_name": student.full_name or "",
                "courses": courses,
            }
        )
