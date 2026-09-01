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
    _programme_batch,
    _reload_session,
    _resolve_timetable_slot_id,
    _schedule_meetings_for_course_units,
    _serialize_course_unit,
    _serialize_session,
)
from .enrollment_cohort import admitted_students_for_program_batch, student_belongs_to_program_batch
from .models import CourseUnit, CourseUnitClassCoordinator, SharedTeachingOffering, TimetableSession
from .permissions import LectureAttendanceAdminPermission
from .shared_teaching import linked_course_unit_ids, resolve_parent_course_unit


def _get_course_unit_with_shared(course_unit_id: int) -> CourseUnit | None:
    """Load course unit; prefer shared/parent joins when schema supports them."""
    base = CourseUnit.objects.select_related(
        "semester",
        "semester__program_batch",
        "program_batch",
        "program_batch__program",
        "shared_teaching_offering",
    )
    try:
        return base.select_related(
            "shared_teaching_offering__parent_course_unit",
        ).get(pk=course_unit_id, is_active=True)
    except CourseUnit.DoesNotExist:
        return None
    except Exception:
        # Local DBs may lag behind shared-parent migration; still load the unit.
        try:
            return base.get(pk=course_unit_id, is_active=True)
        except CourseUnit.DoesNotExist:
            return None


def _canonical_coordinator_course_unit(course_unit: CourseUnit) -> CourseUnit:
    """Shared programme offerings use the parent course unit for coordinators."""
    if not course_unit.shared_teaching_offering_id:
        return course_unit
    try:
        sto = getattr(course_unit, "shared_teaching_offering", None)
        if sto is None:
            sto = SharedTeachingOffering.objects.filter(
                pk=course_unit.shared_teaching_offering_id
            ).first()
        if not sto:
            return course_unit
        parent = resolve_parent_course_unit(sto)
        return parent or course_unit
    except Exception:
        # Missing parent_course_unit column or related schema — use selected unit.
        return course_unit


def _coordinator_resolution_meta(selected: CourseUnit, canonical: CourseUnit) -> dict:
    if selected.pk == canonical.pk:
        return {"is_shared_child": False}
    return {
        "is_shared_child": True,
        "selected_course_unit_id": selected.pk,
        "selected_course_code": selected.code,
        "selected_course_name": selected.name,
        "parent_course_unit_id": canonical.pk,
        "parent_course_code": canonical.code,
        "parent_course_name": canonical.name,
    }


def _coordinator_program_batch_id(student) -> int | None:
    try:
        enrollment = getattr(student, "programme_enrollment", None)
        if enrollment and enrollment.program_batch_id:
            return int(enrollment.program_batch_id)
    except Exception:
        pass
    return None


def _course_unit_on_program_batch(course_unit: CourseUnit, batch_id: int) -> bool:
    if course_unit.program_batch_id == batch_id:
        return True
    sem = getattr(course_unit, "semester", None)
    return bool(sem and sem.program_batch_id == batch_id)


def _attached_course_units_for_coordinator(student, canonical: CourseUnit) -> list[CourseUnit]:
    """
    Operational units a coordinator may open attendance for.

    Shared offerings store the assignment on the parent unit; coordinators only
    act on linked units for their own programme batch (not every programme on
    the shared slot).
    """
    if not canonical.shared_teaching_offering_id:
        return [canonical]

    linked_ids = linked_course_unit_ids(canonical)
    units = list(
        CourseUnit.objects.filter(pk__in=linked_ids, is_active=True)
        .select_related("program_batch", "program_batch__program", "semester")
        .order_by("code", "id")
    )
    batch_id = _coordinator_program_batch_id(student)
    if batch_id:
        filtered = [cu for cu in units if _course_unit_on_program_batch(cu, batch_id)]
        if filtered:
            return filtered
        if _course_unit_on_program_batch(canonical, batch_id):
            return [canonical]
        return []

    return units


def _parent_course_unit_for_assignment(canonical: CourseUnit) -> CourseUnit:
    if not canonical.shared_teaching_offering_id:
        return canonical
    sto = getattr(canonical, "shared_teaching_offering", None)
    if sto is None:
        sto = SharedTeachingOffering.objects.filter(
            pk=canonical.shared_teaching_offering_id
        ).first()
    if sto:
        return resolve_parent_course_unit(sto) or canonical
    return canonical


def _student_display(student) -> dict:
    app = getattr(student, "application", None)
    name = ""
    if app:
        name = f"{getattr(app, 'first_name', '') or ''} {getattr(app, 'last_name', '') or ''}".strip()
    if not name:
        name = getattr(student, "full_name", None) or ""
    section = None
    try:
        section = student.programme_enrollment.teaching_section
    except Exception:
        section = None
    return {
        "id": student.id,
        "reg_no": student.reg_no or "",
        "student_id": student.student_id or "",
        "name": name or student.reg_no or student.student_id or f"Student {student.id}",
        "teaching_section_code": section.code if section else "",
        "teaching_section_name": section.name if section else "",
    }


def _enrolled_cohort_students_for_course_unit(course_unit: CourseUnit):
    """All programme-enrolled students on the canonical course unit's cohort."""
    from admissions.models import AdmittedStudent

    canonical = _canonical_coordinator_course_unit(course_unit)
    program_batch = _programme_batch(canonical)
    if not program_batch or not program_batch.program_id:
        return AdmittedStudent.objects.none(), None, canonical
    qs = (
        admitted_students_for_program_batch(program_batch.program, program_batch)
        .filter(programme_enrollment__status="enrolled")
        .select_related("application", "programme_enrollment__teaching_section")
        .order_by("reg_no", "student_id")
    )
    return qs, program_batch, canonical


def _assert_student_eligible_coordinator(student, course_unit: CourseUnit) -> str | None:
    """Return error message if student cannot be coordinator; None if OK."""
    canonical = _canonical_coordinator_course_unit(course_unit)
    program_batch = _programme_batch(canonical)
    if not program_batch:
        return "Course unit is not linked to a programme batch."
    if not student_belongs_to_program_batch(student, program_batch):
        return "Student must belong to the parent course's programme batch."
    enrollment = getattr(student, "programme_enrollment", None)
    if not enrollment or enrollment.status != "enrolled":
        return "Student must have programme enrollment status Enrolled."
    return None


def _serialize_assignment(row: CourseUnitClassCoordinator, *, student=None) -> dict:
    cu = row.course_unit
    parent = _parent_course_unit_for_assignment(cu)
    attached = _attached_course_units_for_coordinator(student or row.student, cu)
    payload = {
        "id": row.id,
        "is_active": row.is_active,
        "notes": row.notes or "",
        "course_unit": _serialize_course_unit(cu),
        "course_unit_id": cu.id,
        "course_code": cu.code,
        "course_name": cu.name,
        "is_shared_offering": bool(cu.shared_teaching_offering_id),
        "parent_course_unit": _serialize_course_unit(parent),
        "parent_course_unit_id": parent.id,
        "parent_course_code": parent.code,
        "parent_course_name": parent.name,
        "attached_course_units": [_serialize_course_unit(u) for u in attached],
        "attached_course_unit_ids": [u.id for u in attached],
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
    return payload


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
            "course_unit__shared_teaching_offering",
            "course_unit__shared_teaching_offering__parent_course_unit",
            "teaching_section",
            "student",
            "student__application",
            "student__programme_enrollment",
        )
        .order_by("course_unit__code")
    )


def _coordinator_course_unit_ids(student) -> list[int]:
    expanded: set[int] = set()
    rows = CourseUnitClassCoordinator.objects.filter(
        student=student, is_active=True
    ).select_related("course_unit")
    for row in rows:
        for cu in _attached_course_units_for_coordinator(student, row.course_unit):
            expanded.add(cu.pk)
    return list(expanded)


def _assert_student_is_coordinator(student, course_unit: CourseUnit) -> None:
    canonical = _canonical_coordinator_course_unit(course_unit)
    ok = CourseUnitClassCoordinator.objects.filter(
        student=student,
        course_unit=canonical,
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
            selected = _get_course_unit_with_shared(course_unit_id)
            if selected:
                _assert_admin_course_access(request.user, selected)
                canonical = _canonical_coordinator_course_unit(selected)
                qs = qs.filter(course_unit=canonical)
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
                "coordinators": [_serialize_assignment(r, student=r.student) for r in rows],
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
        course_unit = _get_course_unit_with_shared(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)
        canonical = _canonical_coordinator_course_unit(course_unit)

        from admissions.models import AdmittedStudent

        student = (
            AdmittedStudent.objects.filter(pk=student_id)
            .select_related("application", "programme_enrollment")
            .first()
        )
        if not student:
            return Response({"detail": "Student not found."}, status=404)

        eligibility_error = _assert_student_eligible_coordinator(student, course_unit)
        if eligibility_error:
            return Response({"detail": eligibility_error}, status=400)

        teaching_section_id = _parse_int(request.data.get("teaching_section_id"))
        notes = str(request.data.get("notes") or "").strip()[:255]

        existing = CourseUnitClassCoordinator.objects.filter(
            course_unit=canonical,
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
                course_unit=canonical,
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
                "coordinator": _serialize_assignment(row, student=student),
                **_coordinator_resolution_meta(course_unit, canonical),
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
    """Search programme-enrolled students on the course cohort for coordinator assignment."""

    permission_classes = [IsAuthenticated, LectureAttendanceAdminPermission]

    def get(self, request):
        _assert_attendance_admin_write(request.user)
        course_unit_id = _parse_int(request.query_params.get("course_unit_id"))
        if not course_unit_id:
            return Response({"detail": "course_unit_id is required."}, status=400)
        course_unit = _get_course_unit_with_shared(course_unit_id)
        if not course_unit:
            return Response({"detail": "Course unit not found."}, status=404)
        _assert_admin_course_access(request.user, course_unit)

        qs, program_batch, canonical = _enrolled_cohort_students_for_course_unit(course_unit)
        if program_batch is None:
            return Response(
                {"detail": "Course unit is not linked to a programme batch."},
                status=400,
            )

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(reg_no__icontains=search)
                | Q(student_id__icontains=search)
                | Q(application__first_name__icontains=search)
                | Q(application__last_name__icontains=search)
            )
        already = set(
            CourseUnitClassCoordinator.objects.filter(
                course_unit=canonical, is_active=True
            ).values_list("student_id", flat=True)
        )
        students = []
        for s in qs[:100]:
            students.append(
                {
                    **_student_display(s),
                    "already_coordinator": s.id in already,
                }
            )
        return Response(
            {
                "course_unit_id": course_unit_id,
                "program_batch_id": program_batch.id,
                "program_batch_name": program_batch.name,
                "students": students,
                "count": len(students),
                **_coordinator_resolution_meta(course_unit, canonical),
            }
        )


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
                "assignments": [_serialize_assignment(r, student=admitted) for r in rows],
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
        rows = list(_coordinator_assignments_qs(admitted))
        if not rows:
            return Response(
                {
                    "today": today.isoformat(),
                    "date": today.isoformat(),
                    "meetings": [],
                    "assignment_groups": [],
                    "meetings_count": 0,
                    "detail": "You are not assigned as a class coordinator on any course.",
                }
            )

        capture_date = (
            _parse_date(request.query_params.get("date") or request.query_params.get("session_date"))
            or today
        )

        assignment_groups = []
        all_meetings: list[dict] = []
        assigned_ids: set[int] = set()

        for row in rows:
            canonical = row.course_unit
            parent = _parent_course_unit_for_assignment(canonical)
            attached = _attached_course_units_for_coordinator(admitted, canonical)
            attached_ids = [cu.id for cu in attached]
            assigned_ids.update(attached_ids)
            group_meetings = _schedule_meetings_for_course_units(
                attached_ids, from_date=capture_date, to_date=capture_date
            )
            all_meetings.extend(group_meetings)
            assignment_groups.append(
                {
                    "assignment_id": row.id,
                    "parent_course_unit_id": parent.id,
                    "parent_course_code": parent.code,
                    "parent_course_name": parent.name,
                    "parent_course_unit": _serialize_course_unit(parent),
                    "attached_course_units": [_serialize_course_unit(cu) for cu in attached],
                    "attached_course_unit_ids": attached_ids,
                    "meetings": group_meetings,
                    "meetings_count": len(group_meetings),
                }
            )

        all_meetings.sort(key=lambda m: (m["session_date"], m["start_time"], m["course_code"]))
        return Response(
            {
                "today": today.isoformat(),
                "date": capture_date.isoformat(),
                "assignment_groups": assignment_groups,
                "meetings": all_meetings,
                "meetings_count": len(all_meetings),
                "assigned_course_unit_ids": list(assigned_ids),
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
            course_unit = _get_course_unit_with_shared(course_unit_id)
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
