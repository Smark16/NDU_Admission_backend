"""Student class coordinators — open/close lecture attendance check-in only."""

from __future__ import annotations

from django.db.models import Count, Q
from django.utils import timezone as dj_tz
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .attendance_views import (
    LectureAttendanceRecord,
    LectureAttendanceSession,
    _assert_admin_course_access,
    _assert_attendance_admin_write,
    _close_check_in,
    _find_attendance_session,
    _get_course_unit,
    _get_or_create_session_shell,
    _issue_check_in_token,
    _meeting_date_for_slot,
    _normalize_attendance_code,
    _open_check_in,
    _parse_date,
    _parse_int,
    _reload_session,
    _resolve_timetable_slot_id,
    _schedule_meetings_for_course_units,
    _serialize_course_unit,
    _serialize_session,
)
from .models import CourseUnit, CourseUnitClassCoordinator, StudentCourseUnitEnrollment, TimetableSession
from .permissions import LectureAttendanceAdminPermission


def _student_display(student) -> dict:
    app = getattr(student, "application", None)
    name = ""
    if app:
        name = f"{getattr(app, 'first_name', '') or ''} {getattr(app, 'last_name', '') or ''}".strip()
    if not name:
        name = getattr(student, "full_name", None) or ""
    return {
        "id": student.id,
        "reg_no": student.reg_no or "",
        "student_id": student.student_id or "",
        "name": name or student.reg_no or student.student_id or f"Student {student.id}",
    }


def _serialize_assignment(row: CourseUnitClassCoordinator) -> dict:
    cu = row.course_unit
    return {
        "id": row.id,
        "is_active": row.is_active,
        "notes": row.notes or "",
        "course_unit": _serialize_course_unit(cu),
        "course_unit_id": cu.id,
        "course_code": cu.code,
        "course_name": cu.name,
        "student": _student_display(row.student),
        "teaching_section": (
            {
                "id": row.teaching_section.id,
                "code": row.teaching_section.code,
                "name": row.teaching_section.name,
            }
            if row.teaching_section_id
            else None
        ),
        "assigned_at": row.created_at.isoformat() if row.created_at else None,
    }


def _get_admitted_or_404(user):
    from payments.student_portal_finance import get_admitted_student_for_user

    admitted = get_admitted_student_for_user(user)
    if not admitted:
        return None
    return admitted


def _coordinator_assignments_qs(student):
    return (
        CourseUnitClassCoordinator.objects.filter(student=student, is_active=True)
        .select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "teaching_section",
            "student",
            "student__application",
        )
        .order_by("course_unit__code")
    )


def _coordinator_course_unit_ids(student) -> list[int]:
    return list(
        CourseUnitClassCoordinator.objects.filter(student=student, is_active=True)
        .values_list("course_unit_id", flat=True)
        .distinct()
    )


def _assert_student_is_coordinator(student, course_unit: CourseUnit) -> None:
    ok = CourseUnitClassCoordinator.objects.filter(
        student=student,
        course_unit=course_unit,
        is_active=True,
    ).exists()
    if not ok:
        raise PermissionDenied("You are not the class coordinator for this course.")


def _get_coordinator_timetable_slot(student, timetable_session_id) -> TimetableSession:
    try:
        tid = int(timetable_session_id)
    except (TypeError, ValueError):
        raise ValueError("timetable_session_id is required.")
    assigned_ids = _coordinator_course_unit_ids(student)
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
        .first()
    )
    if not slot:
        raise ValueError("Timetable class not found or not assigned to you as coordinator.")
    _assert_student_is_coordinator(student, slot.course_unit)
    return slot


def _resolve_session_for_coordinator(student, data_or_params):
    session_id = data_or_params.get("session_id")
    if session_id:
        session = (
            LectureAttendanceSession.objects.filter(pk=session_id)
            .select_related("course_unit")
            .first()
        )
        if session:
            _assert_student_is_coordinator(student, session.course_unit)
        return session

    course_unit_id = _parse_int(data_or_params.get("course_unit_id"))
    session_date = _parse_date(data_or_params.get("session_date") or data_or_params.get("date"))
    if not course_unit_id or not session_date:
        return None
    course_unit = _get_course_unit(course_unit_id)
    if not course_unit:
        return None
    _assert_student_is_coordinator(student, course_unit)
    try:
        slot = _resolve_timetable_slot_id(data_or_params.get("timetable_session_id"))
    except ValueError:
        slot = None
    return _find_attendance_session(course_unit, session_date, timetable_session=slot)


# ----- Admin: assign / list / remove student coordinators -----


class AdminClassCoordinatorListCreateView(APIView):
    """List or assign student class coordinators for a course unit."""

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        course_unit_id = _parse_int(request.query_params.get("course_unit_id"))
        qs = CourseUnitClassCoordinator.objects.select_related(
            "course_unit",
            "course_unit__semester",
            "course_unit__program_batch",
            "course_unit__program_batch__program",
            "teaching_section",
            "student",
            "student__application",
        ).order_by("course_unit__code", "student__reg_no")
        if course_unit_id:
            qs = qs.filter(course_unit_id=course_unit_id)
            cu = _get_course_unit(course_unit_id)
            if cu:
                _assert_admin_course_access(request.user, cu)
        else:
            from admissions.faculty_scope import filter_course_units_for_user

            allowed = filter_course_units_for_user(
                CourseUnit.objects.filter(is_active=True), request.user
            ).values_list("id", flat=True)
            qs = qs.filter(course_unit_id__in=allowed)
        active_only = str(request.query_params.get("active_only") or "1").lower() not in (
            "0",
            "false",
            "no",
        )
        if active_only:
            qs = qs.filter(is_active=True)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(student__reg_no__icontains=search)
                | Q(student__student_id__icontains=search)
                | Q(student__application__first_name__icontains=search)
                | Q(student__application__last_name__icontains=search)
                | Q(course_unit__code__icontains=search)
                | Q(course_unit__name__icontains=search)
            )
        rows = list(qs[:200])
        return Response(
            {
                "count": len(rows),
                "coordinators": [_serialize_assignment(r) for r in rows],
            }
        )

    def post(self, request):
        _assert_attendance_admin_write(request.user)
        course_unit_id = _parse_int(request.data.get("course_unit_id"))
        student_id = _parse_int(request.data.get("student_id"))
        if not course_unit_id or not student_id:
            return Response(
                {"detail": "course_unit_id and student_id are required."},
                status=400,
            )
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)

        from admissions.models import AdmittedStudent

        student = AdmittedStudent.objects.filter(pk=student_id).select_related("application").first()
        if not student:
            return Response({"detail": "Student not found."}, status=404)

        enrolled = StudentCourseUnitEnrollment.objects.filter(
            course_unit=course_unit,
            student=student,
            status="enrolled",
        ).exists()
        if not enrolled:
            return Response(
                {
                    "detail": (
                        "Student must be enrolled on this course unit before they can "
                        "be assigned as class coordinator."
                    )
                },
                status=400,
            )

        teaching_section_id = _parse_int(request.data.get("teaching_section_id"))
        notes = str(request.data.get("notes") or "").strip()[:255]

        existing = CourseUnitClassCoordinator.objects.filter(
            course_unit=course_unit,
            student=student,
            teaching_section_id=teaching_section_id,
        ).first()
        created = existing is None
        if existing:
            existing.is_active = True
            existing.assigned_by = request.user
            if notes:
                existing.notes = notes
            existing.teaching_section_id = teaching_section_id
            existing.save()
            row = existing
        else:
            row = CourseUnitClassCoordinator.objects.create(
                course_unit=course_unit,
                student=student,
                teaching_section_id=teaching_section_id,
                is_active=True,
                assigned_by=request.user,
                notes=notes,
            )

        row = (
            CourseUnitClassCoordinator.objects.select_related(
                "course_unit",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
                "teaching_section",
                "student",
                "student__application",
            ).get(pk=row.pk)
        )
        return Response(
            {
                "created": created,
                "coordinator": _serialize_assignment(row),
            },
            status=201 if created else 200,
        )


class AdminClassCoordinatorDetailView(APIView):
    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def delete(self, request, pk: int):
        _assert_attendance_admin_write(request.user)
        row = (
            CourseUnitClassCoordinator.objects.select_related("course_unit")
            .filter(pk=pk)
            .first()
        )
        if not row:
            return Response({"detail": "Assignment not found."}, status=404)
        _assert_admin_course_access(request.user, row.course_unit)
        hard = str(request.query_params.get("hard") or "").lower() in ("1", "true", "yes")
        if hard:
            row.delete()
            return Response({"detail": "Coordinator assignment removed."})
        row.is_active = False
        row.save(update_fields=["is_active", "updated_at"])
        return Response({"detail": "Coordinator deactivated."})


class AdminClassCoordinatorCandidatesView(APIView):
    """Search enrolled students on a course unit for coordinator assignment."""

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        course_unit_id = _parse_int(request.query_params.get("course_unit_id"))
        if not course_unit_id:
            return Response({"detail": "course_unit_id is required."}, status=400)
        course_unit = _get_course_unit(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)

        search = (request.query_params.get("search") or "").strip()
        qs = (
            StudentCourseUnitEnrollment.objects.filter(
                course_unit=course_unit,
                status="enrolled",
            )
            .select_related("student", "student__application")
            .order_by("student__reg_no", "student__student_id")
        )
        if search:
            qs = qs.filter(
                Q(student__reg_no__icontains=search)
                | Q(student__student_id__icontains=search)
                | Q(student__application__first_name__icontains=search)
                | Q(student__application__last_name__icontains=search)
            )
        already = set(
            CourseUnitClassCoordinator.objects.filter(
                course_unit=course_unit, is_active=True
            ).values_list("student_id", flat=True)
        )
        students = []
        for enr in qs[:50]:
            s = enr.student
            students.append(
                {
                    **_student_display(s),
                    "already_coordinator": s.id in already,
                }
            )
        return Response({"course_unit_id": course_unit_id, "students": students})


# ----- Student coordinator: schedule + open/close check-in -----


class StudentCoordinatorMeView(APIView):
    """Courses this student is assigned to coordinate."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        admitted = _get_admitted_or_404(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)
        rows = list(_coordinator_assignments_qs(admitted))
        return Response(
            {
                "is_class_coordinator": bool(rows),
                "assignments": [_serialize_assignment(r) for r in rows],
                "count": len(rows),
            }
        )


class StudentCoordinatorScheduleView(APIView):
    """Today's (or selected day) timetable meetings the coordinator can open."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        admitted = _get_admitted_or_404(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        today = dj_tz.localdate()
        assigned_ids = _coordinator_course_unit_ids(admitted)
        if not assigned_ids:
            return Response(
                {
                    "today": today.isoformat(),
                    "date": today.isoformat(),
                    "meetings": [],
                    "meetings_count": 0,
                    "detail": "You are not assigned as a class coordinator on any course.",
                }
            )

        capture_date = (
            _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
            or today
        )
        meetings = _schedule_meetings_for_course_units(
            assigned_ids, from_date=capture_date, to_date=capture_date
        )
        return Response(
            {
                "today": today.isoformat(),
                "date": capture_date.isoformat(),
                "meetings": meetings,
                "meetings_count": len(meetings),
                "assigned_course_unit_ids": assigned_ids,
            }
        )


class StudentCoordinatorOpenCheckInView(APIView):
    """Open student self-check-in for a class the coordinator owns."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        admitted = _get_admitted_or_404(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        timetable_slot = None
        raw_tid = request.data.get("timetable_session_id")
        if raw_tid not in (None, "", 0, "0"):
            try:
                timetable_slot = _get_coordinator_timetable_slot(admitted, raw_tid)
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
            course_unit_id = _parse_int(request.data.get("course_unit_id"))
            session_date = _parse_date(request.data.get("session_date") or request.data.get("date"))
            if not course_unit_id or not session_date:
                return Response(
                    {"detail": "Pick a scheduled class from your coordinator timetable."},
                    status=400,
                )
            course_unit = _get_course_unit(course_unit_id)
            if not course_unit:
                return Response({"detail": "Course unit not found."}, status=404)
            try:
                _assert_student_is_coordinator(admitted, course_unit)
            except PermissionDenied as exc:
                return Response({"detail": str(exc.detail)}, status=403)

        today = dj_tz.localdate()
        if session_date < today:
            return Response(
                {
                    "detail": "Student registration is closed for past class dates.",
                    "registration_closed": True,
                },
                status=400,
            )
        if session_date > today:
            return Response(
                {
                    "detail": "Open student registration on the class day only.",
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
                "course_unit",
                "taken_by",
                "course_unit__semester",
                "course_unit__program_batch",
                "course_unit__program_batch__program",
            )
            .annotate(record_count=Count("records"))
            .get(pk=session.pk)
        )
        payload = _serialize_session(session, include_records=False)
        code = _normalize_attendance_code(session.check_in_token) or session.check_in_token
        payload["attendance_code"] = code
        payload["token"] = code
        return Response(payload)


class StudentCoordinatorCheckInCodeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        admitted = _get_admitted_or_404(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        try:
            session = _resolve_session_for_coordinator(admitted, request.query_params)
        except PermissionDenied as exc:
            return Response({"detail": str(exc.detail)}, status=403)

        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)
        if not session.student_check_in_open:
            return Response(
                {
                    "session_id": session.id,
                    "check_in_open": False,
                    "attendance_code": "",
                    "detail": "Check-in is not open.",
                }
            )

        session = _issue_check_in_token(session, force=False)
        code = _normalize_attendance_code(session.check_in_token) or session.check_in_token
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
                "attendance_code": code,
                "token": code,
            }
        )


class StudentCoordinatorCloseCheckInView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        admitted = _get_admitted_or_404(request.user)
        if not admitted:
            return Response({"detail": "Admitted student profile not found."}, status=404)

        try:
            session = _resolve_session_for_coordinator(admitted, request.data)
        except PermissionDenied as exc:
            return Response({"detail": str(exc.detail)}, status=403)

        if not session:
            return Response({"detail": "Attendance session not found."}, status=404)

        session = _close_check_in(session)
        return Response(_serialize_session(_reload_session(session), include_records=False))
